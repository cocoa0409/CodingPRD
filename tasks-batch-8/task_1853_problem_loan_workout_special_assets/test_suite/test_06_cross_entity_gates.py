"""Cross-entity state dependencies: impairment finalization gated on the owning
case's tdr_status, and collateral release gated on the loan's balance/case closure.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_loan_accounting_headers, make_special_assets_manager_headers,
    make_workout_officer_headers,
    setup_case_in_impairment_review, setup_case_in_action_plan,
    make_borrower_with_loan, open_workout_case, make_collateral, make_accepted_appraisal,
    create_impairment_tdr_dcf_payload, create_impairment_cecl_payload,
)
from test_helpers.api_client import api_client


# ===========================================================================
# Difficulty / cross_entity_state_dependency /
#   impairment_finalize_gated_on_case_tdr_status
# ===========================================================================

def _setup_tdr_rejected_case_14():
    return setup_case_in_impairment_review(
        officer_id="officer-14", manager_id="mgr-14", committee_id="cc-14",
        borrower_overrides={"legal_name": "Maple Leaf Senior Care", "tax_id": "12-0000002",
                            "naics_code": "623312", "internal_risk_rating": 6,
                            "guarantor_name": "", "guarantor_net_worth_cents": 0},
        loan_overrides={"loan_number": "LN-1313", "original_principal_cents": 25000000,
                        "contractual_rate_bps": 875, "days_past_due": 61},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 6},
        plan_overrides={"plan_text": "Mod no concession",
                        "target_resolution_date": "2027-02-20T00:00:00Z", "milestone_count": 1},
        proposal_overrides={"proposal_kind": "MODIFICATION", "concession_rate_bps": 875,
                            "term_extension_months": 12, "principal_forgiveness_cents": 0,
                            "borrower_concession_cents": 200000},
        concession=False,
    )


def test_tdr_dcf_finalize_blocked_when_case_tdr_rejected(api):
    """PRD §3.6: "or `TDR_DCF`, the discounted-cash-flow approach, which is permitted
    only when the case's `tdr_status` is `TDR_CONFIRMED` — finalizing a `TDR_DCF`
    assessment without that confirmation is rejected with
    `ERR_TDR_METHOD_REQUIRES_TDR` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/impairment_finalize_gated_on_case_tdr_status
    """
    ctx = _setup_tdr_rejected_case_14()
    loan, case = ctx["loan"], ctx["case"]
    assert ctx["case"]["tdr_status"] == "TDR_REJECTED"
    acct_h = make_loan_accounting_headers("acct-14")

    imp = get_success_data(api_client.create_impairment(
        loan["id"], case["id"],
        create_impairment_tdr_dcf_payload(
            probability_of_default_bps=2000, loss_given_default_bps=3000,
            expected_cash_flows=[{"period_index": 12, "amount_cents": 24000000}]),
        acct_h))
    res = api_client.finalize_impairment(loan["id"], case["id"], imp["id"], acct_h)
    validate_error(res, ApiErrorId.ERR_TDR_METHOD_REQUIRES_TDR.value, expected_status=422)


def test_cecl_finalize_allowed_on_same_tdr_rejected_case(api):
    """PRD §3.6: "Each assessment declares a `method`: `CECL`, the
    probability-weighted expected-loss approach, which is always available during
    impairment review; or `TDR_DCF`, the discounted-cash-flow approach, which is
    permitted only when the case's `tdr_status` is `TDR_CONFIRMED` — finalizing a
    `TDR_DCF` assessment without that confirmation is rejected with
    `ERR_TDR_METHOD_REQUIRES_TDR` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/impairment_finalize_gated_on_case_tdr_status
    """
    ctx = _setup_tdr_rejected_case_14()
    loan, case = ctx["loan"], ctx["case"]
    acct_h = make_loan_accounting_headers("acct-14")

    # CECL is always available during IMPAIRMENT_REVIEW regardless of tdr_status.
    imp = get_success_data(api_client.create_impairment(
        loan["id"], case["id"],
        create_impairment_cecl_payload(probability_of_default_bps=2000, loss_given_default_bps=3000),
        acct_h))
    finalized = validate_success(api_client.finalize_impairment(
        loan["id"], case["id"], imp["id"], acct_h), 200)
    assert finalized["status"] == "FINALIZED"
    assert finalized["is_active"] is True
    # 25,000,000 * 2000 * 3000 / 10^8 = 1,500,000
    assert finalized["computed_reserve_cents"] == 1500000


# ===========================================================================
# Difficulty / cross_entity_state_dependency / collateral_release_gated_on_loan_balance
# ===========================================================================

def _setup_pledged_appraised_collateral_with_open_case():
    """PLEDGED collateral with an accepted 80,000,000 appraisal (20% haircut) on a
    70,000,000-current loan whose case is still open (WATCHLIST)."""
    borrower, loan = make_borrower_with_loan(
        "officer-15",
        borrower_overrides={"legal_name": "Northgate Retail", "tax_id": "12-0000003",
                            "naics_code": "445110", "internal_risk_rating": 7},
        loan_overrides={"loan_number": "LN-1414", "original_principal_cents": 70000000,
                        "contractual_rate_bps": 925, "days_past_due": 68})
    officer_h = make_workout_officer_headers("officer-15")
    item = make_collateral(loan["id"], officer_h, collateral_type="CRE_REAL_ESTATE",
                           description="Strip mall", liquidation_discount_bps=2000)
    case, officer_h, manager_h = open_workout_case(
        loan["id"], officer_id="officer-15", manager_id="mgr-15",
        entry_trigger="DELINQUENCY_60", risk_rating_at_entry=7)
    item, appraisal = make_accepted_appraisal(
        loan["id"], item["id"], desk_id="appr-1",
        appraisal_overrides={"appraised_value_cents": 80000000,
                             "effective_date": "2026-07-01T00:00:00Z"})
    return borrower, loan, case, item, manager_h


def test_release_blocked_while_loan_encumbered_and_case_open(api):
    """PRD §3.5: "A `SpecialAssetsManager` may release an item, which requires it to
    be `PLEDGED` (else `ERR_COLLATERAL_NOT_PLEDGED`) and requires the collateral to
    be genuinely unencumbered: either the loan's `current_principal_cents` has
    reached zero or the workout case is already `CLOSED` — otherwise the release is
    blocked with `ERR_COLLATERAL_ENCUMBERED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/collateral_release_gated_on_loan_balance
    """
    borrower, loan, case, item, manager_h = _setup_pledged_appraised_collateral_with_open_case()

    res = api_client.release_collateral(loan["id"], item["id"], manager_h)
    validate_error(res, ApiErrorId.ERR_COLLATERAL_ENCUMBERED.value, expected_status=422)

    # The accepted appraisal had revalued the item: 80,000,000 x (10000-2000)/10000.
    item_after = validate_success(api_client.get_collateral(loan["id"], item["id"], manager_h), 200)
    assert item_after["current_liquidation_value_cents"] == 64000000
    assert item_after["status"] == "PLEDGED"


def test_release_allowed_once_principal_reaches_zero(api):
    """PRD §3.5: "A `SpecialAssetsManager` may release an item, which requires it to
    be `PLEDGED` (else `ERR_COLLATERAL_NOT_PLEDGED`) and requires the collateral to
    be genuinely unencumbered: either the loan's `current_principal_cents` has
    reached zero or the workout case is already `CLOSED` — otherwise the release is
    blocked with `ERR_COLLATERAL_ENCUMBERED` (HTTP 422). Release moves the item to
    `RELEASED` and recomputes loss-given-default without it."

    Design: Difficulty/cross_entity_state_dependency/collateral_release_gated_on_loan_balance
    """
    borrower, loan = make_borrower_with_loan(
        "officer-15b",
        loan_overrides={"original_principal_cents": 70000000, "contractual_rate_bps": 925,
                        "days_past_due": 68})
    officer_h = make_workout_officer_headers("officer-15b")
    item = make_collateral(loan["id"], officer_h, collateral_type="CRE_REAL_ESTATE",
                           description="Strip mall", liquidation_discount_bps=2000)
    case, officer_h, manager_h = open_workout_case(
        loan["id"], officer_id="officer-15b", manager_id="mgr-15b",
        entry_trigger="DELINQUENCY_60", risk_rating_at_entry=7)
    # Charge off the entire principal so current_principal_cents reaches 0.
    acct_h = make_loan_accounting_headers("acct-15b")
    get_success_data(api_client.create_charge_off(
        loan["id"], case["id"], {"amount_cents": 70000000, "reason_code": "CONFIRMED_LOSS"},
        acct_h))
    loan_after = validate_success(api_client.get_loan(loan["id"], acct_h), 200)
    assert loan_after["current_principal_cents"] == 0

    released = validate_success(api_client.release_collateral(loan["id"], item["id"], manager_h), 200)
    assert released["status"] == "RELEASED"
