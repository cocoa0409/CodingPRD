"""Corner coverage — error catalog: second referral accept, charge-off exceeding
current principal, and exit decision with no active referral.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_loan_accounting_headers, make_legal_counsel_headers,
    make_workout_officer_headers, make_special_assets_manager_headers,
    setup_case_in_legal, make_borrower_with_loan, open_workout_case, make_borrower,
    create_charge_off_payload, create_legal_referral_payload,
    create_exit_decision_payload, create_workout_case_payload, create_loan_payload,
    assert_charge_off,
)
from test_helpers.api_client import api_client


def test_error_referral_not_pending_second_accept(api):
    """PRD §3.7: "Counsel accepts it — requiring `PENDING_COUNSEL` (else
    `ERR_REFERRAL_NOT_PENDING`) — and at acceptance the statute deadline is
    re-checked against the logical clock: a deadline that is no longer strictly in
    the future means the limitations window has closed and acceptance fails with
    `ERR_STATUTE_EXPIRED` (HTTP 422). An accepted referral is `ACTIVE`, and from
    there counsel either settles or dismisses it; both require `ACTIVE` and are
    otherwise refused with `ERR_REFERRAL_NOT_ACTIVE`."

    Design: Corner/errors/error_referral_not_pending_second_accept
    """
    ctx = setup_case_in_legal(
        officer_id="officer-e3", manager_id="mgr-e3", counsel_id="counsel-e3",
        borrower_overrides={"legal_name": "Referral Twice Co", "tax_id": "55-0000022",
                            "naics_code": "541714", "internal_risk_rating": 8},
        loan_overrides={"loan_number": "LN-E03", "original_principal_cents": 5000000,
                        "contractual_rate_bps": 800, "days_past_due": 70},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 8},
        plan_overrides={"plan_text": "Ref", "target_resolution_date": "2027-01-30T00:00:00Z",
                        "milestone_count": 1},
        referral_overrides={"referral_kind": "NOTE_SALE_PREP", "demand_amount_cents": 0,
                            "statute_deadline": "2028-01-01T00:00:00Z",
                            "decision_rationale": "Prep"},
    )
    loan, case, referral = ctx["loan"], ctx["case"], ctx["referral"]
    assert referral["status"] == "ACTIVE"

    res = api_client.accept_referral(loan["id"], case["id"], referral["id"], ctx["counsel_h"])
    validate_error(res, ApiErrorId.ERR_REFERRAL_NOT_PENDING.value, expected_status=409)


def test_error_chargeoff_exceeds_current_principal(api):
    """PRD §3.8: "A charge-off records an `amount_cents` of principal being written
    down — it must be greater than zero and no more than the loan's
    `current_principal_cents` at booking time, or it fails with `ERR_FISCAL_LIMIT`
    (HTTP 422) — and a `reason_code` of `CONFIRMED_LOSS`, `STATUTORY`, or
    `PARTIAL_IMPAIRMENT`. The system stamps `booked_at` from the logical clock,
    computes `is_partial` as true exactly when the amount is strictly less than the
    principal outstanding at booking, moves the amount out of
    `current_principal_cents` and into `charged_off_principal_cents`, and recomputes
    the case's loss-given-default."

    Design: Corner/errors/error_chargeoff_exceeds_current_principal
    """
    officer_h = make_workout_officer_headers("officer-e4")
    borrower = make_borrower(officer_h, legal_name="Overcharge Co", tax_id="55-0000023",
                             naics_code="541715", internal_risk_rating=8)
    loan = get_success_data(api_client.create_loan(
        {"borrower_id": borrower["id"], "loan_number": "LN-E04",
         "original_principal_cents": 5000000, "contractual_rate_bps": 800,
         "days_past_due": 75},
        officer_h))
    case = get_success_data(api_client.create_workout_case(
        loan["id"],
        {"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 8,
         "case_officer_id": "officer-e4"},
        officer_h))
    acct_h = make_loan_accounting_headers("acct-e4")

    # current principal is 5,000,000: one cent more is rejected.
    res = api_client.create_charge_off(
        loan["id"], case["id"],
        create_charge_off_payload(amount_cents=5000001, reason_code="CONFIRMED_LOSS"),
        acct_h)
    validate_error(res, ApiErrorId.ERR_FISCAL_LIMIT.value, expected_status=422)

    # Exactly the full current principal succeeds and is not partial.
    event = validate_success(api_client.create_charge_off(
        loan["id"], case["id"],
        create_charge_off_payload(amount_cents=5000000, reason_code="CONFIRMED_LOSS"),
        acct_h), 201)
    assert_charge_off(event)
    assert event["is_partial"] is False

    loan_after = validate_success(api_client.get_loan(loan["id"], acct_h), 200)
    assert loan_after["current_principal_cents"] == 0
    assert loan_after["charged_off_principal_cents"] == 5000000


def test_error_no_active_referral_on_exit_from_legal(api):
    """PRD §3.9: "From `LEGAL`, the decision requires the case to be `LEGAL` (else
    `ERR_CASE_NOT_LEGAL`) and requires at least one referral on the case to stand
    `ACTIVE` or `SETTLED` (else `ERR_NO_ACTIVE_REFERRAL`), and any of the four paths
    may be chosen."

    Design: Corner/errors/error_no_active_referral_on_exit_from_legal
    """
    ctx = setup_case_in_legal(
        officer_id="officer-e5", manager_id="mgr-e5", counsel_id="counsel-e5",
        borrower_overrides={"legal_name": "No Active Ref Co", "tax_id": "55-0000024",
                            "naics_code": "541716", "internal_risk_rating": 8},
        loan_overrides={"loan_number": "LN-E05", "original_principal_cents": 4000000,
                        "contractual_rate_bps": 800, "days_past_due": 75},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 8},
        plan_overrides={"plan_text": "Dismiss path",
                        "target_resolution_date": "2027-02-28T00:00:00Z", "milestone_count": 1},
        referral_overrides={"referral_kind": "FORECLOSURE", "demand_amount_cents": 0,
                            "statute_deadline": "2028-01-01T00:00:00Z",
                            "decision_rationale": "Will dismiss"},
    )
    loan, case, referral = ctx["loan"], ctx["case"], ctx["referral"]
    get_success_data(api_client.dismiss_referral(loan["id"], case["id"], referral["id"], ctx["counsel_h"]))

    # Only a DISMISSED referral remains: no ACTIVE or SETTLED referral on the case.
    res = api_client.create_exit_decision(
        loan["id"], case["id"],
        create_exit_decision_payload(chosen_path="FORECLOSURE",
                                     npv_foreclosure_cents=3000000,
                                     npv_deed_in_lieu_cents=2000000,
                                     override_justification=""),
        ctx["manager_h"])
    validate_error(res, ApiErrorId.ERR_NO_ACTIVE_REFERRAL.value, expected_status=409)
