"""Corner coverage — validations: auth header gate, nonaccrual 90-day threshold,
and the action-plan future-target temporal rule.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_workout_officer_headers, make_loan_accounting_headers,
    make_borrower_with_loan, make_borrower, open_workout_case,
    create_borrower_payload, create_loan_payload, create_action_plan_payload,
)
from test_helpers.api_client import api_client


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a role the system does
    not recognize, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    PRD §2.11: "1. User-context headers present and role recognized
    (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`)."

    Design: Corner/validations/missing_auth_headers_rejected
    """
    res = api_client.create_borrower(
        {"legal_name": "No Auth", "tax_id": "55-0000017", "naics_code": "541620",
         "internal_risk_rating": 5},
        headers={"Content-Type": "application/json"})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
                   expected_status=400)


def test_nonaccrual_threshold_90_days(api):
    """PRD §3.1: "An aging refresh overwrites `days_past_due` with the supplied value
    and re-evaluates the nonaccrual flag: `nonaccrual` becomes true when the
    refreshed `days_past_due` reaches at least ninety days, and it is also forced
    true — regardless of delinquency — whenever any workout case on the loan is in
    `LEGAL`. The flag clears only when both conditions release together:
    `days_past_due` falls back below ninety days and no case on the loan remains in
    `LEGAL`."

    Design: Corner/validations/nonaccrual_threshold_90_days
    """
    officer_h = make_workout_officer_headers("officer-v1")
    borrower = make_borrower(officer_h, legal_name="Aging Co", tax_id="55-0000018",
                             naics_code="541690", internal_risk_rating=4)
    loan = get_success_data(api_client.create_loan(
        {"borrower_id": borrower["id"], "loan_number": "LN-V01",
         "original_principal_cents": 8000000, "contractual_rate_bps": 700,
         "days_past_due": 0},
        officer_h))
    acct_h = make_loan_accounting_headers("acct-v1")

    at_89 = validate_success(api_client.aging_refresh(loan["id"], {"days_past_due": 89}, acct_h), 200)
    assert at_89["nonaccrual"] is False, "89 days is below the ninety-day threshold"

    at_90 = validate_success(api_client.aging_refresh(loan["id"], {"days_past_due": 90}, acct_h), 200)
    assert at_90["nonaccrual"] is True, "at least ninety days flips nonaccrual true (inclusive)"


def test_action_plan_temporal_target_must_be_future(api):
    """PRD §3.2: "The target date must lie strictly after the current logical clock
    time; a date at or before the clock is rejected with `ERR_INVALID_TEMPORAL` (HTTP
    422)."
    PRD §2.5: "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and
    before any explicit set operation the clock continues to read that default — it
    never silently falls back to wall-clock time."

    Design: Corner/validations/action_plan_temporal_target_must_be_future
    """
    officer_h = make_workout_officer_headers("officer-v2")
    borrower = make_borrower(officer_h, legal_name="Temporal Co", tax_id="55-0000019",
                             naics_code="541711", internal_risk_rating=7)
    loan = get_success_data(api_client.create_loan(
        {"borrower_id": borrower["id"], "loan_number": "LN-V02",
         "original_principal_cents": 9000000, "contractual_rate_bps": 800,
         "days_past_due": 61},
        officer_h))
    case = get_success_data(api_client.create_workout_case(
        loan["id"],
        {"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 7,
         "case_officer_id": "officer-v2"},
        officer_h))

    # Target equal to the clock default (2026-08-01T00:00:00Z) is not strictly after.
    res = api_client.create_action_plan(
        loan["id"], case["id"],
        create_action_plan_payload(case["version"], plan_text="Past target",
                                   target_resolution_date="2026-08-01T00:00:00Z",
                                   milestone_count=1),
        officer_h)
    validate_error(res, ApiErrorId.ERR_INVALID_TEMPORAL.value, expected_status=422)
