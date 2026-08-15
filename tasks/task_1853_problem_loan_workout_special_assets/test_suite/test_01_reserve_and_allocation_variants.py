"""Dual-variant calculations: reserve measurement (CECL vs TDR_DCF) and
recovery allocation (CHRONOLOGICAL vs WATERFALL), plus combinatorial formula
instances (forgiveness cap state dependence; waterfall costs-tier rounding).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_loan_accounting_headers, make_credit_committee_headers,
    make_workout_officer_headers, make_special_assets_manager_headers,
    make_legal_counsel_headers,
    setup_case_in_negotiation, setup_case_in_impairment_review, setup_case_in_legal,
    make_borrower_with_loan, open_workout_case,
    create_impairment_cecl_payload, create_impairment_tdr_dcf_payload,
    create_proposal_payload, create_charge_off_payload, create_recovery_payload,
    create_action_plan_payload, create_legal_referral_payload,
)
from test_helpers.api_client import api_client


# ===========================================================================
# Difficulty / dual_variant_calc /
#   reserve_measurement_cecl_vs_tdr_dcf_divergence
# ===========================================================================

def _setup_tdr_confirmed_case_100m():
    """Case in IMPAIRMENT_REVIEW with TDR_CONFIRMED on a 100,000,000-cent, 1200bps loan."""
    return setup_case_in_impairment_review(
        officer_id="officer-1", manager_id="mgr-1", committee_id="cc-1",
        borrower_overrides={"legal_name": "Acme Properties LLC", "tax_id": "12-3456789",
                            "naics_code": "531120", "internal_risk_rating": 8,
                            "guarantor_name": "G Smith", "guarantor_net_worth_cents": 50000000},
        loan_overrides={"loan_number": "LN-1001", "original_principal_cents": 100000000,
                        "contractual_rate_bps": 1200, "days_past_due": 75},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 8},
        proposal_overrides={"proposal_kind": "MODIFICATION", "concession_rate_bps": 600,
                            "term_extension_months": 24, "principal_forgiveness_cents": 0,
                            "borrower_concession_cents": 0},
        concession=True,
    )


def test_cecl_and_tdr_dcf_produce_divergent_reserves_latest_wins(api):
    """PRD §3.6: "The two methods measure different things — probability-weighted
    loss versus contractual-cash-flow shortfall at the original effective rate — so
    on the same case with the same principal they generally produce different
    reserves; whichever assessment reached `FINALIZED` most recently is the one that
    counts."
    PRD §3.6: "Under `CECL`, `computed_reserve_cents` is the loan's
    `current_principal_cents` at finalization multiplied by
    `probability_of_default_bps` and by `loss_given_default_bps`, divided by one
    hundred million, rounded half up to whole cents: one multiplication chain, one
    division, one rounding."

    Design: Difficulty/dual_variant_calc/reserve_measurement_cecl_vs_tdr_dcf_divergence
    """
    ctx = _setup_tdr_confirmed_case_100m()
    loan, case = ctx["loan"], ctx["case"]
    acct_h = make_loan_accounting_headers("acct-1")

    # Finalize CECL: 100,000,000 * 2500 * 4000 / 10^8 = 10,000,000
    cecl = get_success_data(api_client.create_impairment(
        loan["id"], case["id"],
        create_impairment_cecl_payload(probability_of_default_bps=2500, loss_given_default_bps=4000),
        acct_h))
    cecl_fin = validate_success(api_client.finalize_impairment(
        loan["id"], case["id"], cecl["id"], acct_h), 200)
    assert cecl_fin["computed_reserve_cents"] == 10000000, (
        f"CECL reserve should be 10000000, got {cecl_fin['computed_reserve_cents']}")

    # Finalize TDR_DCF on same case: PV of flows at original 1200bps monthly.
    dcf = get_success_data(api_client.create_impairment(
        loan["id"], case["id"],
        create_impairment_tdr_dcf_payload(
            probability_of_default_bps=2500, loss_given_default_bps=4000,
            expected_cash_flows=[
                {"period_index": 1, "amount_cents": 5000000},
                {"period_index": 12, "amount_cents": 40000000},
                {"period_index": 24, "amount_cents": 50000000},
            ]),
        acct_h))
    dcf_fin = validate_success(api_client.finalize_impairment(
        loan["id"], case["id"], dcf["id"], acct_h), 200)
    assert dcf_fin["computed_reserve_cents"] == 20173230, (
        f"TDR_DCF reserve should be 20173230, got {dcf_fin['computed_reserve_cents']}")

    # The two methods diverge on identical case + principal.
    assert cecl_fin["computed_reserve_cents"] != dcf_fin["computed_reserve_cents"]

    # Case reserve reflects the latest finalization.
    case_after = validate_success(api_client.get_workout_case(loan["id"], case["id"], acct_h), 200)
    assert case_after["impairment_reserve_cents"] == 20173230


def test_second_finalize_supersedes_first_assessment(api):
    """PRD §3.6: "Exactly one assessment per case may be active at a time: any
    previously `FINALIZED` assessment on the same case moves to `SUPERSEDED` and its
    `is_active` flips false the moment a newer one finalizes."

    Design: Difficulty/dual_variant_calc/reserve_measurement_cecl_vs_tdr_dcf_divergence
    """
    ctx = _setup_tdr_confirmed_case_100m()
    loan, case = ctx["loan"], ctx["case"]
    acct_h = make_loan_accounting_headers("acct-1")

    cecl = get_success_data(api_client.create_impairment(
        loan["id"], case["id"], create_impairment_cecl_payload(), acct_h))
    validate_success(api_client.finalize_impairment(loan["id"], case["id"], cecl["id"], acct_h), 200)

    dcf = get_success_data(api_client.create_impairment(
        loan["id"], case["id"],
        create_impairment_tdr_dcf_payload(expected_cash_flows=[
            {"period_index": 1, "amount_cents": 5000000},
            {"period_index": 12, "amount_cents": 40000000},
            {"period_index": 24, "amount_cents": 50000000},
        ]),
        acct_h))
    dcf_fin = validate_success(api_client.finalize_impairment(
        loan["id"], case["id"], dcf["id"], acct_h), 200)

    assert dcf_fin["is_active"] is True
    cecl_after = validate_success(api_client.get_impairment_flat(cecl["id"], acct_h), 200)
    assert cecl_after["is_active"] is False
    assert cecl_after["status"] == "SUPERSEDED"


# ===========================================================================
# Difficulty / dual_variant_calc /
#   recovery_allocation_chronological_vs_waterfall_divergence
# ===========================================================================

def _setup_legal_case_with_chargeoff_20m():
    """LEGAL case on a 100,000,000 loan after a 20,000,000 charge-off."""
    ctx = setup_case_in_legal(
        officer_id="officer-9", manager_id="mgr-9", counsel_id="counsel-9",
        borrower_overrides={"legal_name": "Beacon Retail Inc", "tax_id": "98-7654321",
                            "naics_code": "452210", "internal_risk_rating": 9,
                            "guarantor_name": "", "guarantor_net_worth_cents": 0},
        loan_overrides={"loan_number": "LN-2002", "original_principal_cents": 100000000,
                        "contractual_rate_bps": 900, "days_past_due": 120},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 9},
        plan_overrides={"plan_text": "Legal track", "target_resolution_date": "2027-01-01T00:00:00Z",
                        "milestone_count": 2},
        referral_overrides={"referral_kind": "FORECLOSURE", "demand_amount_cents": 0,
                            "statute_deadline": "2028-01-01T00:00:00Z",
                            "decision_rationale": "Value-maximizing path"},
    )
    acct_h = make_loan_accounting_headers("acct-9")
    get_success_data(api_client.create_charge_off(
        ctx["loan"]["id"], ctx["case"]["id"],
        create_charge_off_payload(amount_cents=20000000, reason_code="CONFIRMED_LOSS"),
        acct_h))
    return ctx, acct_h


def test_chronological_recovery_fills_charged_off_bucket_first(api):
    """PRD §3.8: "Under `CHRONOLOGICAL`, the bank's regulatory default, the recovery
    first repays charged-off principal: the smaller of the recovery amount and the
    loan's `charged_off_principal_cents` goes to that bucket. The remainder then
    repays current principal: the smaller of what is left and the loan's
    `current_principal_cents`."

    Design: Difficulty/dual_variant_calc/recovery_allocation_chronological_vs_waterfall_divergence
    """
    ctx, acct_h = _setup_legal_case_with_chargeoff_20m()
    loan, case = ctx["loan"], ctx["case"]

    validate_success(api_client.create_recovery(
        loan["id"], case["id"],
        create_recovery_payload(amount_cents=30000000, recovery_source="NOTE_SALE_PROCEEDS",
                                allocation_mode="CHRONOLOGICAL"),
        acct_h), 201)

    loan_after = validate_success(api_client.get_loan(loan["id"], acct_h), 200)
    assert loan_after["charged_off_principal_cents"] == 0, (
        "30,000,000 CHRONOLOGICAL fills the 20,000,000 charged-off bucket first")
    assert loan_after["current_principal_cents"] == 70000000, (
        "remaining 10,000,000 spills to current principal (80,000,000 -> 70,000,000)")


def test_waterfall_then_diverges_via_costs_tier(api):
    """PRD §3.8: "Under `WATERFALL`, costs come first: the costs tier receives the
    smaller of the recovery amount and ten percent of the recovery amount, with that
    ten-percent figure rounded half up to whole cents. The remainder then repays
    charged-off principal up to the outstanding `charged_off_principal_cents`, then
    current principal up to the outstanding `current_principal_cents`, and any final
    excess again lands in `unapplied_cash_cents`."
    PRD §3.8: "Because the bucket order differs, the two variants split the same
    recovery differently whenever both principal buckets are non-zero."

    Design: Difficulty/dual_variant_calc/recovery_allocation_chronological_vs_waterfall_divergence
    """
    ctx, acct_h = _setup_legal_case_with_chargeoff_20m()
    loan, case = ctx["loan"], ctx["case"]

    # First a CHRONOLOGICAL recovery of 30,000,000.
    validate_success(api_client.create_recovery(
        loan["id"], case["id"],
        create_recovery_payload(amount_cents=30000000, recovery_source="NOTE_SALE_PROCEEDS",
                                allocation_mode="CHRONOLOGICAL"),
        acct_h), 201)
    mid = validate_success(api_client.get_loan(loan["id"], acct_h), 200)
    assert mid["charged_off_principal_cents"] == 0
    assert mid["current_principal_cents"] == 70000000

    # Then a WATERFALL recovery of 30,000,000 on the post-chrono state
    # (charged_off=0, current=70,000,000): costs tier = half_up(10% of 30,000,000)
    # = 3,000,000; remainder 27,000,000 all lands on current principal.
    validate_success(api_client.create_recovery(
        loan["id"], case["id"],
        create_recovery_payload(amount_cents=30000000, recovery_source="NOTE_SALE_PROCEEDS",
                                allocation_mode="WATERFALL"),
        acct_h), 201)
    after = validate_success(api_client.get_loan(loan["id"], acct_h), 200)
    assert after["charged_off_principal_cents"] == 0
    assert after["current_principal_cents"] == 43000000, (
        f"70,000,000 - 27,000,000 = 43,000,000 expected, got {after['current_principal_cents']}")


# ===========================================================================
# Difficulty / combinatorial_formula / forgiveness_cap_state_dependent_threshold
# ===========================================================================

def _setup_cap_scenario(forgiveness_cents, officer_id="officer-3", manager_id="mgr-3",
                        committee_id="cc-3", accounting_id="acct-3"):
    """100,000,000-original loan, 20,000,000 already charged off, case in NEGOTIATION
    with a proposal at COMMITTEE_REVIEW carrying the given forgiveness."""
    ctx = setup_case_in_negotiation(
        officer_id=officer_id, manager_id=manager_id,
        borrower_overrides={"legal_name": "Capstone Holdings", "tax_id": "11-1111111",
                            "naics_code": "237110", "internal_risk_rating": 7,
                            "guarantor_name": "", "guarantor_net_worth_cents": 0},
        loan_overrides={"loan_number": "LN-3003", "original_principal_cents": 100000000,
                        "contractual_rate_bps": 800, "days_past_due": 95},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 7},
        plan_overrides={"plan_text": "Restructure with forgiveness",
                        "target_resolution_date": "2027-03-01T00:00:00Z", "milestone_count": 1},
    )
    loan, case = ctx["loan"], ctx["case"]
    acct_h = make_loan_accounting_headers(accounting_id)
    get_success_data(api_client.create_charge_off(
        loan["id"], case["id"],
        create_charge_off_payload(amount_cents=20000000, reason_code="PARTIAL_IMPAIRMENT"),
        acct_h))
    case = get_success_data(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]))
    prop = get_success_data(api_client.create_proposal(
        loan["id"], case["id"],
        create_proposal_payload(case["version"], proposal_kind="RESTRUCTURE",
                                concession_rate_bps=500, term_extension_months=12,
                                principal_forgiveness_cents=forgiveness_cents,
                                borrower_concession_cents=0),
        ctx["officer_h"]))
    get_success_data(api_client.submit_proposal(loan["id"], case["id"], prop["id"], ctx["officer_h"]))
    get_success_data(api_client.escalate_proposal(loan["id"], case["id"], prop["id"], ctx["officer_h"]))
    ctx["proposal"] = prop
    ctx["committee_h"] = make_credit_committee_headers(committee_id)
    return ctx


def test_forgiveness_at_exact_cap_approved_state_dependent(api):
    """PRD §3.3: "the sum of the loan's `charged_off_principal_cents` already booked
    and this proposal's `principal_forgiveness_cents` must not exceed one quarter of
    the loan's `original_principal_cents` — computed as the original principal times
    twenty-five hundred basis points divided by ten thousand, with any fractional cent
    discarded. The ceiling is inclusive: a sum exactly equal to the cap is allowed,
    and only a sum strictly greater is refused with `ERR_FORGIVENESS_CAP_EXCEEDED`
    (HTTP 422)."

    Design: Difficulty/combinatorial_formula/forgiveness_cap_state_dependent_threshold
    """
    ctx = _setup_cap_scenario(forgiveness_cents=5000000)
    loan, case, prop = ctx["loan"], ctx["case"], ctx["proposal"]
    res = api_client.committee_approve_proposal(loan["id"], case["id"], prop["id"], ctx["committee_h"])
    approved = validate_success(res, 200)
    # cumulative_after == 20,000,000 + 5,000,000 == 25,000,000 == cap exactly (inclusive)
    assert approved["status"] == "APPROVED"


def test_forgiveness_cap_depends_on_accumulated_chargeoffs(api):
    """PRD §3.3: "Approval requires the proposal to be sitting in `COMMITTEE_REVIEW`
    (else `ERR_PROPOSAL_NOT_COMMITTEE_REVIEW`) and enforces the bank's cumulative
    forgiveness ceiling: the sum of the loan's `charged_off_principal_cents` already
    booked and this proposal's `principal_forgiveness_cents` must not exceed one
    quarter of the loan's `original_principal_cents` — computed as the original
    principal times twenty-five hundred basis points divided by ten thousand, with any
    fractional cent discarded."

    Design: Difficulty/combinatorial_formula/forgiveness_cap_state_dependent_threshold
    """
    # Same proposal size (5,000,000) fails when prior charge-offs are larger:
    # 21,000,000 + 5,000,000 = 26,000,000 > 25,000,000 cap.
    ctx = setup_case_in_negotiation(
        officer_id="officer-3b", manager_id="mgr-3b",
        loan_overrides={"original_principal_cents": 100000000, "contractual_rate_bps": 800,
                        "days_past_due": 95},
    )
    loan, case = ctx["loan"], ctx["case"]
    acct_h = make_loan_accounting_headers("acct-3b")
    get_success_data(api_client.create_charge_off(
        loan["id"], case["id"],
        create_charge_off_payload(amount_cents=21000000, reason_code="PARTIAL_IMPAIRMENT"),
        acct_h))
    case = get_success_data(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]))
    prop = get_success_data(api_client.create_proposal(
        loan["id"], case["id"],
        create_proposal_payload(case["version"], proposal_kind="RESTRUCTURE",
                                concession_rate_bps=500, term_extension_months=12,
                                principal_forgiveness_cents=5000000,
                                borrower_concession_cents=0),
        ctx["officer_h"]))
    get_success_data(api_client.submit_proposal(loan["id"], case["id"], prop["id"], ctx["officer_h"]))
    get_success_data(api_client.escalate_proposal(loan["id"], case["id"], prop["id"], ctx["officer_h"]))
    res = api_client.committee_approve_proposal(
        loan["id"], case["id"], prop["id"], make_credit_committee_headers("cc-3b"))
    validate_error(res, ApiErrorId.ERR_FORGIVENESS_CAP_EXCEEDED.value)


# ===========================================================================
# Difficulty / combinatorial_formula / recovery_waterfall_costs_tier_nested_rounding
# ===========================================================================

def _setup_legal_case_odd_principal():
    """LEGAL case on a 10,000,001-cent loan with no charge-offs yet."""
    ctx = setup_case_in_legal(
        officer_id="officer-4", manager_id="mgr-4", counsel_id="counsel-4",
        borrower_overrides={"legal_name": "Delta Manufacturing", "tax_id": "22-2222222",
                            "naics_code": "332710", "internal_risk_rating": 8,
                            "guarantor_name": "", "guarantor_net_worth_cents": 0},
        loan_overrides={"loan_number": "LN-4004", "original_principal_cents": 10000001,
                        "contractual_rate_bps": 1100, "days_past_due": 100},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 8},
        plan_overrides={"plan_text": "Liquidate", "target_resolution_date": "2027-01-15T00:00:00Z",
                        "milestone_count": 1},
        referral_overrides={"referral_kind": "NOTE_SALE_PREP", "demand_amount_cents": 0,
                            "statute_deadline": "2028-06-01T00:00:00Z",
                            "decision_rationale": "Note sale prep"},
    )
    return ctx, make_loan_accounting_headers("acct-4")


def test_waterfall_costs_tier_rounded_once_on_total(api):
    """PRD §3.8: "Under `WATERFALL`, costs come first: the costs tier receives the
    smaller of the recovery amount and ten percent of the recovery amount, with that
    ten-percent figure rounded half up to whole cents. The remainder then repays
    charged-off principal up to the outstanding `charged_off_principal_cents`, then
    current principal up to the outstanding `current_principal_cents`, and any final
    excess again lands in `unapplied_cash_cents`."
    PRD §2.6: "In the cost-first recovery allocation variant, only the costs tier
    involves a rounding — half up to whole cents — while every other bucket amount is
    an exact integer by construction."

    Note on expected values: the PRD pins half-up rounding for the ten-percent
    figure. 10% of 10,000,001 is 1,000,000.1, which rounds half-up to 1,000,000.
    The costs tier therefore diverts 1,000,000; the remaining 9,000,001 repays
    current principal, leaving current_principal_cents == 1,000,000 and
    unapplied_cash_cents == 0.

    Design: Difficulty/combinatorial_formula/recovery_waterfall_costs_tier_nested_rounding
    """
    ctx, acct_h = _setup_legal_case_odd_principal()
    loan, case = ctx["loan"], ctx["case"]

    validate_success(api_client.create_recovery(
        loan["id"], case["id"],
        create_recovery_payload(amount_cents=10000001, recovery_source="NOTE_SALE_PROCEEDS",
                                allocation_mode="WATERFALL"),
        acct_h), 201)

    loan_after = validate_success(api_client.get_loan(loan["id"], acct_h), 200)
    # costs tier = half_up(10,000,001 * 0.10) = 1,000,000; to_current = 9,000,001.
    assert loan_after["current_principal_cents"] == 1000000, (
        f"Expected current principal 1,000,000 after costs tier, got "
        f"{loan_after['current_principal_cents']}")
    case_after = validate_success(api_client.get_workout_case(loan["id"], case["id"], acct_h), 200)
    assert case_after["unapplied_cash_cents"] == 0


def test_waterfall_costs_tier_rounds_half_up_not_truncated(api):
    """PRD §2.6: "In the cost-first recovery allocation variant, only the costs tier
    involves a rounding — half up to whole cents — while every other bucket amount is
    an exact integer by construction."
    PRD §3.8: "Under `WATERFALL`, costs come first: the costs tier receives the
    smaller of the recovery amount and ten percent of the recovery amount, with that
    ten-percent figure rounded half up to whole cents."

    A recovery of 10,000,005 with empty charged-off bucket and ample current
    principal: the costs tier is half_up(1,000,000.5) = 1,000,001 (half-up pushes the
    exact half up), distinguishing half-up from truncation.

    Design: Difficulty/combinatorial_formula/recovery_waterfall_costs_tier_nested_rounding
    """
    ctx = setup_case_in_legal(
        officer_id="officer-4b", manager_id="mgr-4b", counsel_id="counsel-4b",
        loan_overrides={"original_principal_cents": 20000005, "contractual_rate_bps": 1100,
                        "days_past_due": 100},
        referral_overrides={"referral_kind": "NOTE_SALE_PREP", "demand_amount_cents": 0,
                            "statute_deadline": "2028-06-01T00:00:00Z",
                            "decision_rationale": "Note sale prep"},
    )
    loan, case = ctx["loan"], ctx["case"]
    acct_h = make_loan_accounting_headers("acct-4b")

    validate_success(api_client.create_recovery(
        loan["id"], case["id"],
        create_recovery_payload(amount_cents=10000005, recovery_source="NOTE_SALE_PROCEEDS",
                                allocation_mode="WATERFALL"),
        acct_h), 201)

    loan_after = validate_success(api_client.get_loan(loan["id"], acct_h), 200)
    # costs = half_up(1,000,000.5) = 1,000,001; remainder 9,000,004 -> current.
    assert loan_after["current_principal_cents"] == 20000005 - 9000004, (
        f"Expected {20000005 - 9000004}, got {loan_after['current_principal_cents']}")
