"""Transitive cascades: consummate-forgiveness depth-3 cascade and the
guarantor-settle depth-2 cascade.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    make_loan_accounting_headers, make_legal_counsel_headers,
    setup_case_in_negotiation, setup_case_in_legal,
    make_borrower_with_loan, open_workout_case,
    create_proposal_payload, create_charge_off_payload, create_legal_referral_payload,
    create_action_plan_payload,
    make_credit_committee_headers, make_workout_officer_headers,
    make_special_assets_manager_headers,
)
from test_helpers.api_client import api_client


# ===========================================================================
# Difficulty / transitive_cascade / consummate_forgiveness_cascade_depth3
# ===========================================================================

def _setup_approved_forgiveness_proposal():
    """NEGOTIATION case with an APPROVED proposal carrying 4,000,000 forgiveness on a
    60,000,000 loan with no collateral (LGD tracks principal exactly)."""
    ctx = setup_case_in_negotiation(
        officer_id="officer-7", manager_id="mgr-7",
        borrower_overrides={"legal_name": "Greenfield Farms", "tax_id": "55-5555555",
                            "naics_code": "111110", "internal_risk_rating": 8,
                            "guarantor_name": "", "guarantor_net_worth_cents": 0},
        loan_overrides={"loan_number": "LN-7007", "original_principal_cents": 60000000,
                        "contractual_rate_bps": 1050, "days_past_due": 80},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 8},
        plan_overrides={"plan_text": "Restructure", "target_resolution_date": "2027-06-01T00:00:00Z",
                        "milestone_count": 2},
    )
    loan, case = ctx["loan"], ctx["case"]
    case = get_success_data(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]))
    prop = get_success_data(api_client.create_proposal(
        loan["id"], case["id"],
        create_proposal_payload(case["version"], proposal_kind="RESTRUCTURE",
                                concession_rate_bps=700, term_extension_months=18,
                                principal_forgiveness_cents=4000000,
                                borrower_concession_cents=0),
        ctx["officer_h"]))
    get_success_data(api_client.submit_proposal(loan["id"], case["id"], prop["id"], ctx["officer_h"]))
    get_success_data(api_client.escalate_proposal(loan["id"], case["id"], prop["id"], ctx["officer_h"]))
    get_success_data(api_client.committee_approve_proposal(
        loan["id"], case["id"], prop["id"], make_credit_committee_headers("cc-7")))
    ctx["proposal"] = prop
    return ctx


def test_consummate_books_forgiveness_chargeoff_and_moves_balances(api):
    """PRD §3.4: "And when the consummated terms include any principal forgiveness,
    the system books a charge-off event for exactly `principal_forgiveness_cents`
    under reason code `PARTIAL_IMPAIRMENT` — a charge-off like any other, so it draws
    the loan's `current_principal_cents` down by the forgiven amount, raises
    `charged_off_principal_cents` by the same amount, and forces a recomputation of
    the case's `loss_given_default_cents`, all in the cascade style of §2.9."

    Design: Difficulty/transitive_cascade/consummate_forgiveness_cascade_depth3
    """
    ctx = _setup_approved_forgiveness_proposal()
    loan, case, prop = ctx["loan"], ctx["case"], ctx["proposal"]

    consummated = validate_success(api_client.consummate_proposal(
        loan["id"], case["id"], prop["id"], ctx["officer_h"]), 200)
    assert consummated["status"] == "CONSUMMATED"
    assert consummated["tdr_flag"] is True, "concession (700 < 1050) + difficulty (dpd 80) => TDR"

    # Hop 1: cascaded charge-off event exists for exactly the forgiveness amount.
    charge_offs, meta = validate_paginated(api_client.list_charge_offs(
        loan["id"], case["id"], make_loan_accounting_headers("acct-7")))
    assert meta["total_count"] == 1
    assert charge_offs[0]["amount_cents"] == 4000000
    assert charge_offs[0]["reason_code"] == "PARTIAL_IMPAIRMENT"

    # Hop 2: loan balances moved by the forgiven amount.
    loan_after = validate_success(api_client.get_loan(loan["id"], ctx["officer_h"]), 200)
    assert loan_after["current_principal_cents"] == 56000000
    assert loan_after["charged_off_principal_cents"] == 4000000


def test_consummate_cascade_recomputes_case_state_and_tdr(api):
    """PRD §3.4: "The effects fan out from there. The proposal moves to `CONSUMMATED`.
    The case moves from `NEGOTIATION` to `IMPAIRMENT_REVIEW`, and its `tdr_status`
    resolves from `PENDING_EVALUATION` to `TDR_CONFIRMED` when the flag is true or
    `TDR_REJECTED` when it is false. When the flag is true, the loan's `is_tdr` flips
    to true and remains true until payoff."
    PRD §3.5: "The loss-given-default on a workout case is the bank's uncovered
    exposure: the loan's `current_principal_cents` minus the sum of
    `current_liquidation_value_cents` across every collateral item on that loan whose
    status is `PLEDGED` or `UNDER_REVALUATION` — items `RELEASED` or `LIQUIDATED` no
    longer count toward cover — floored at zero so it can never go negative."

    Design: Difficulty/transitive_cascade/consummate_forgiveness_cascade_depth3
    """
    ctx = _setup_approved_forgiveness_proposal()
    loan, case, prop = ctx["loan"], ctx["case"], ctx["proposal"]

    validate_success(api_client.consummate_proposal(loan["id"], case["id"], prop["id"], ctx["officer_h"]), 200)

    # Hop 3: case state and LGD recomputed (no collateral -> LGD tracks principal).
    case_after = validate_success(api_client.get_workout_case(loan["id"], case["id"], ctx["officer_h"]), 200)
    assert case_after["status"] == "IMPAIRMENT_REVIEW"
    assert case_after["tdr_status"] == "TDR_CONFIRMED"
    assert case_after["loss_given_default_cents"] == 56000000

    loan_after = validate_success(api_client.get_loan(loan["id"], ctx["officer_h"]), 200)
    assert loan_after["is_tdr"] is True


# ===========================================================================
# Difficulty / transitive_cascade / guarantor_settle_cascade_depth2
# ===========================================================================

def _setup_active_guarantor_referral():
    """LEGAL case with an ACTIVE GUARANTOR_PURSUITS referral demanding 8,000,000 on a
    60,000,000-original loan after a 10,000,000 charge-off (current 50,000,000)."""
    ctx = setup_case_in_negotiation(
        officer_id="officer-8", manager_id="mgr-8",
        borrower_overrides={"legal_name": "Harborview Hotels", "tax_id": "66-6666666",
                            "naics_code": "721110", "internal_risk_rating": 9,
                            "guarantor_name": "J Guarantor",
                            "guarantor_net_worth_cents": 30000000},
        loan_overrides={"loan_number": "LN-8008", "original_principal_cents": 60000000,
                        "contractual_rate_bps": 1100, "days_past_due": 110},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 9},
        plan_overrides={"plan_text": "Pursue guarantor",
                        "target_resolution_date": "2027-07-01T00:00:00Z", "milestone_count": 2},
    )
    loan, case = ctx["loan"], ctx["case"]
    acct_h = make_loan_accounting_headers("acct-8")
    get_success_data(api_client.create_charge_off(
        loan["id"], case["id"],
        create_charge_off_payload(amount_cents=10000000, reason_code="CONFIRMED_LOSS"),
        acct_h))
    counsel_h = make_legal_counsel_headers("counsel-8")
    referral = get_success_data(api_client.create_legal_referral(
        loan["id"], case["id"],
        create_legal_referral_payload(referral_kind="GUARANTOR_PURSUITS",
                                      target_guarantor_name="J Guarantor",
                                      demand_amount_cents=8000000,
                                      statute_deadline="2028-01-01T00:00:00Z",
                                      decision_rationale=""),
        ctx["officer_h"]))
    referral = get_success_data(api_client.accept_referral(
        loan["id"], case["id"], referral["id"], counsel_h))
    ctx["referral"] = referral
    ctx["counsel_h"] = counsel_h
    return ctx, acct_h


def test_guarantor_settle_books_linked_chronological_recovery(api):
    """PRD §3.7: "For a `GUARANTOR_PURSUITS` referral, settling books a linked
    recovery event in the same operation: a recovery whose `recovery_source` is
    `GUARANTOR_SETTLEMENT`, whose amount is the `settled_amount_cents`, and whose
    allocation is the chronological order — the allocation machinery of §3.8 then
    runs, moving the loan's principal balances and recomputing the case's
    loss-given-default."

    Design: Difficulty/transitive_cascade/guarantor_settle_cascade_depth2
    """
    ctx, acct_h = _setup_active_guarantor_referral()
    loan, case, referral = ctx["loan"], ctx["case"], ctx["referral"]

    settled = validate_success(api_client.settle_referral(
        loan["id"], case["id"], referral["id"],
        {"settled_amount_cents": 8000000}, ctx["counsel_h"]), 200)
    assert settled["status"] == "SETTLED"

    # Hop 1: linked recovery event synthesized with CHRONOLOGICAL allocation.
    recoveries, meta = validate_paginated(api_client.list_recoveries(loan["id"], case["id"], acct_h))
    assert meta["total_count"] == 1
    rec = recoveries[0]
    assert rec["recovery_source"] == "GUARANTOR_SETTLEMENT"
    assert rec["amount_cents"] == 8000000
    assert rec["allocation_mode"] == "CHRONOLOGICAL"


def test_guarantor_settle_reallocates_balances_and_recomputes_lgd(api):
    """PRD §3.7: "For a `GUARANTOR_PURSUITS` referral, settling books a linked
    recovery event in the same operation: a recovery whose `recovery_source` is
    `GUARANTOR_SETTLEMENT`, whose amount is the `settled_amount_cents`, and whose
    allocation is the chronological order — the allocation machinery of §3.8 then
    runs, moving the loan's principal balances and recomputing the case's
    loss-given-default."
    PRD §3.8: "Under `CHRONOLOGICAL`, the bank's regulatory default, the recovery
    first repays charged-off principal: the smaller of the recovery amount and the
    loan's `charged_off_principal_cents` goes to that bucket."

    Design: Difficulty/transitive_cascade/guarantor_settle_cascade_depth2
    """
    ctx, acct_h = _setup_active_guarantor_referral()
    loan, case, referral = ctx["loan"], ctx["case"], ctx["referral"]

    validate_success(api_client.settle_referral(
        loan["id"], case["id"], referral["id"],
        {"settled_amount_cents": 8000000}, ctx["counsel_h"]), 200)

    # Hop 2: 8,000,000 repays the 10,000,000 charged-off bucket first.
    loan_after = validate_success(api_client.get_loan(loan["id"], acct_h), 200)
    assert loan_after["charged_off_principal_cents"] == 2000000
    assert loan_after["current_principal_cents"] == 50000000

    # Hop 2b: LGD recomputed from the new current principal (no collateral).
    case_after = validate_success(api_client.get_workout_case(loan["id"], case["id"], acct_h), 200)
    assert case_after["loss_given_default_cents"] == 50000000
