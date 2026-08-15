"""Compensating invariants: principal-ledger conservation across a charge-off and
its compensating recovery; LGD reconciliation across appraisal supersession.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_loan_accounting_headers, make_appraisal_desk_headers,
    make_workout_officer_headers,
    setup_case_in_legal, make_borrower_with_loan, open_workout_case,
    make_collateral, make_accepted_appraisal,
    create_charge_off_payload, create_recovery_payload, create_appraisal_payload,
    assert_loan_principal_ledger_invariants,
)
from test_helpers.api_client import api_client


# ===========================================================================
# Difficulty / compensating_invariant / chargeoff_recovery_principal_conservation
# ===========================================================================

def _setup_legal_case_50m():
    ctx = setup_case_in_legal(
        officer_id="officer-17", manager_id="mgr-17", counsel_id="counsel-17",
        borrower_overrides={"legal_name": "Quarrystone Materials", "tax_id": "12-0000006",
                            "naics_code": "212311", "internal_risk_rating": 8,
                            "guarantor_name": "", "guarantor_net_worth_cents": 0},
        loan_overrides={"loan_number": "LN-1717", "original_principal_cents": 50000000,
                        "contractual_rate_bps": 1000, "days_past_due": 100},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 8},
        plan_overrides={"plan_text": "Legal", "target_resolution_date": "2027-04-10T00:00:00Z",
                        "milestone_count": 1},
        referral_overrides={"referral_kind": "NOTE_SALE_PREP", "demand_amount_cents": 0,
                            "statute_deadline": "2028-01-01T00:00:00Z",
                            "decision_rationale": "Prep"},
    )
    return ctx, make_loan_accounting_headers("acct-17")


def test_chargeoff_then_compensating_recovery_conserves_principal_total(api):
    """PRD §3.8: "The system stamps `booked_at` from the logical clock, computes
    `is_partial` as true exactly when the amount is strictly less than the principal
    outstanding at booking, moves the amount out of `current_principal_cents` and
    into `charged_off_principal_cents`, and recomputes the case's
    loss-given-default."
    PRD §3.8: "Under `CHRONOLOGICAL`, the bank's regulatory default, the recovery
    first repays charged-off principal: the smaller of the recovery amount and the
    loan's `charged_off_principal_cents` goes to that bucket. The remainder then
    repays current principal: the smaller of what is left and the loan's
    `current_principal_cents`. Anything still left over is not an error — it
    accumulates into the case's `unapplied_cash_cents`."

    Design: Difficulty/compensating_invariant/chargeoff_recovery_principal_conservation
    """
    ctx, acct_h = _setup_legal_case_50m()
    loan, case = ctx["loan"], ctx["case"]
    assert loan["current_principal_cents"] == 50000000
    assert loan["charged_off_principal_cents"] == 0

    get_success_data(api_client.create_charge_off(
        loan["id"], case["id"],
        create_charge_off_payload(amount_cents=12000000, reason_code="CONFIRMED_LOSS"),
        acct_h))
    mid = validate_success(api_client.get_loan(loan["id"], acct_h), 200)
    assert mid["current_principal_cents"] == 38000000
    assert mid["charged_off_principal_cents"] == 12000000
    assert_loan_principal_ledger_invariants(mid)
    # Invariant: the pair conserves the ledger total at 50,000,000.
    assert mid["current_principal_cents"] + mid["charged_off_principal_cents"] == 50000000

    get_success_data(api_client.create_recovery(
        loan["id"], case["id"],
        create_recovery_payload(amount_cents=12000000, recovery_source="NOTE_SALE_PROCEEDS",
                                allocation_mode="CHRONOLOGICAL"),
        acct_h))
    after = validate_success(api_client.get_loan(loan["id"], acct_h), 200)
    # The recovery repays the charged-off bucket exactly.
    assert after["charged_off_principal_cents"] == 0
    assert after["current_principal_cents"] == 38000000
    # PRD §3.8: the charged-off portion is subtracted from charged_off_principal_cents
    # — a recovery retires debt, so the ledger total drops by the recovered amount.
    assert after["current_principal_cents"] + after["charged_off_principal_cents"] == 38000000


def test_compensating_recovery_leaves_no_unapplied_cash(api):
    """PRD §3.8: "Anything still left over is not an error — it accumulates into the
    case's `unapplied_cash_cents`."
    PRD §3.8: "Whichever variant runs, the charged-off portion is subtracted from
    `charged_off_principal_cents` and the current-principal portion from
    `current_principal_cents`, and the case's loss-given-default is recomputed."

    Design: Difficulty/compensating_invariant/chargeoff_recovery_principal_conservation
    """
    ctx, acct_h = _setup_legal_case_50m()
    loan, case = ctx["loan"], ctx["case"]

    get_success_data(api_client.create_charge_off(
        loan["id"], case["id"],
        create_charge_off_payload(amount_cents=12000000, reason_code="CONFIRMED_LOSS"),
        acct_h))
    get_success_data(api_client.create_recovery(
        loan["id"], case["id"],
        create_recovery_payload(amount_cents=12000000, recovery_source="NOTE_SALE_PROCEEDS",
                                allocation_mode="CHRONOLOGICAL"),
        acct_h))

    case_after = validate_success(api_client.get_workout_case(loan["id"], case["id"], acct_h), 200)
    assert case_after["unapplied_cash_cents"] == 0, (
        "a recovery fully absorbed by the charged-off bucket leaves no excess")
    # LGD tracks current principal with no collateral.
    assert case_after["loss_given_default_cents"] == 38000000


# ===========================================================================
# Difficulty / compensating_invariant /
#   appraisal_supersede_lgd_reconciliation_invariant
# ===========================================================================

def _setup_loan_case_collateral_100m():
    borrower, loan = make_borrower_with_loan(
        "officer-18",
        borrower_overrides={"legal_name": "Riverbend Winery", "tax_id": "12-0000007",
                            "naics_code": "312130", "internal_risk_rating": 7},
        loan_overrides={"loan_number": "LN-1818", "original_principal_cents": 100000000,
                        "contractual_rate_bps": 975, "days_past_due": 70})
    officer_h = make_workout_officer_headers("officer-18")
    item = make_collateral(loan["id"], officer_h, collateral_type="CRE_REAL_ESTATE",
                           description="Winery estate", liquidation_discount_bps=2000)
    case, officer_h, manager_h = open_workout_case(
        loan["id"], officer_id="officer-18", manager_id="mgr-18",
        entry_trigger="DELINQUENCY_60", risk_rating_at_entry=7)
    return borrower, loan, case, item, officer_h


def test_first_accepted_appraisal_sets_cover_and_lgd(api):
    """PRD §3.5: "The loss-given-default on a workout case is the bank's uncovered
    exposure: the loan's `current_principal_cents` minus the sum of
    `current_liquidation_value_cents` across every collateral item on that loan whose
    status is `PLEDGED` or `UNDER_REVALUATION` — items `RELEASED` or `LIQUIDATED` no
    longer count toward cover — floored at zero so it can never go negative. It
    starts at zero and is recomputed on every appraisal acceptance, every charge-off
    booking, every principal recovery, and every collateral liquidation or release."
    PRD §3.5: "`current_liquidation_value_cents` becomes that value multiplied by ten
    thousand minus the item's `liquidation_discount_bps`, divided by ten thousand,
    rounded half up to whole cents — multiply first, divide once, round once, with no
    intermediate rounding of the discount factor."

    Design: Difficulty/compensating_invariant/appraisal_supersede_lgd_reconciliation_invariant
    """
    borrower, loan, case, item, officer_h = _setup_loan_case_collateral_100m()
    item, _ = make_accepted_appraisal(
        loan["id"], item["id"], desk_id="appr-3",
        appraisal_overrides={"appraised_value_cents": 80000000,
                             "effective_date": "2026-07-15T00:00:00Z"})
    # 80,000,000 x 80% = 64,000,000 cover.
    assert item["current_liquidation_value_cents"] == 64000000

    case_after = validate_success(api_client.get_workout_case(loan["id"], case["id"], officer_h), 200)
    assert case_after["loss_given_default_cents"] == 36000000
    # Invariant: LGD + cover == current principal when cover <= principal.
    assert case_after["loss_given_default_cents"] + item["current_liquidation_value_cents"] == 100000000


def test_superseding_appraisal_revalues_cover_without_drift(api):
    """PRD §3.5: "Acceptance moves the appraisal from `SUBMITTED` to its terminal
    `ACCEPTED` state and revalues the item: `current_appraised_value_cents` becomes
    the accepted value, and `current_liquidation_value_cents` becomes that value
    multiplied by ten thousand minus the item's `liquidation_discount_bps`, divided
    by ten thousand, rounded half up to whole cents — multiply first, divide once,
    round once, with no intermediate rounding of the discount factor. The item
    returns to `PLEDGED`, and the case's loss-given-default is recomputed."

    Design: Difficulty/compensating_invariant/appraisal_supersede_lgd_reconciliation_invariant
    """
    borrower, loan, case, item, officer_h = _setup_loan_case_collateral_100m()
    item, _ = make_accepted_appraisal(
        loan["id"], item["id"], desk_id="appr-3",
        appraisal_overrides={"appraised_value_cents": 80000000,
                             "effective_date": "2026-07-15T00:00:00Z"})

    # A second appraisal supersedes the value basis: 50,000,000 x 80% = 40,000,000.
    item2, _ = make_accepted_appraisal(
        loan["id"], item["id"], desk_id="appr-3",
        appraisal_overrides={"appraised_value_cents": 50000000,
                             "effective_date": "2026-07-20T00:00:00Z"})
    assert item2["current_appraised_value_cents"] == 50000000
    assert item2["current_liquidation_value_cents"] == 40000000

    case_after = validate_success(api_client.get_workout_case(loan["id"], case["id"], officer_h), 200)
    assert case_after["loss_given_default_cents"] == 60000000, (
        "LGD must reflect only the latest accepted valuation — no drift from the "
        "superseded 80,000,000 appraisal")
    assert case_after["loss_given_default_cents"] + item2["current_liquidation_value_cents"] == 100000000
