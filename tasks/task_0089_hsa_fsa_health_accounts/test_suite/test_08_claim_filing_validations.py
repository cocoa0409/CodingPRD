"""Claim-filing and plan-year validations: expense qualification, service-window,
filing-window, grace-period extension, duplicate-claim, and relief-mode coherence.

Translates Corner/validations instances.
"""
from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    setup_active_hsa, setup_active_fsa, file_claim,
    set_clock, create_plan_year, create_participant, create_and_activate_fsa,
    create_plan_year_payload, ApiErrorId, make_participant_headers,
)

ADMIN = TEST_USERS["plan_admin_headers"]


def test_dependent_care_claim_on_hsa_not_qualified(api):
    """PRD §3.4: "`DEPENDENT_CARE` is permitted only on a DCFSA ... a `DEPENDENT_CARE` claim
    against an HSA or Health FSA, or any medical-category claim against a DCFSA, is rejected
    with `ERR_EXPENSE_NOT_QUALIFIED` (HTTP 422)."

    Design: Corner/validations/expense_not_qualified_dependent_care_on_hsa
    """
    py, p, acc = setup_active_hsa(elected_amount_cents=437500)
    resp = api.create_claim(
        {"account_id": acc["id"], "service_date": "2026-04-01",
         "expense_category": "DEPENDENT_CARE", "claimed_amount_cents": 20000,
         "substantiated": True},
        make_participant_headers(p["id"]))
    validate_error(resp, ApiErrorId.ERR_EXPENSE_NOT_QUALIFIED.value)


def test_service_date_before_coverage_start_outside_window(api):
    """PRD §3.4: "the `service_date` must fall within the account's effective service window
    — from `coverage_start` through `coverage_end` ... and a date outside that window is
    rejected with `ERR_SERVICE_DATE_OUTSIDE_WINDOW` (HTTP 422)."

    service_date 2025-12-31 precedes coverage_start 2026-01-01.

    Design: Corner/validations/service_date_before_window_returns_outside_window
    """
    py, p, acc = setup_active_fsa(account_type="HEALTH_FSA", elected_amount_cents=100000)
    resp = api.create_claim(
        {"account_id": acc["id"], "service_date": "2025-12-31",
         "expense_category": "MEDICAL", "claimed_amount_cents": 20000,
         "substantiated": True},
        make_participant_headers(p["id"]))
    validate_error(resp, ApiErrorId.ERR_SERVICE_DATE_OUTSIDE_WINDOW.value)


def test_filing_after_run_out_end_returns_filing_window_closed(api):
    """PRD §3.4: "the filing must be timely: the current server date must be on or before the
    account's effective filing deadline, which is `run_out_end` ... a filing after the
    deadline is rejected with `ERR_FILING_WINDOW_CLOSED` (HTTP 422)."

    An in-window service_date (2026-04-01) filed when the clock is 2027-04-01 (past
    run_out_end 2027-03-31) is rejected — distinct from the service-window check.

    Design: Corner/validations/filing_after_run_out_end_returns_filing_window_closed
    """
    py, p, acc = setup_active_fsa(account_type="HEALTH_FSA", elected_amount_cents=100000)
    set_clock("2027-04-01T00:00:00Z")
    resp = api.create_claim(
        {"account_id": acc["id"], "service_date": "2026-04-01",
         "expense_category": "MEDICAL", "claimed_amount_cents": 20000,
         "substantiated": True},
        make_participant_headers(p["id"]))
    validate_error(resp, ApiErrorId.ERR_FILING_WINDOW_CLOSED.value)


def test_grace_period_extends_service_window(api):
    """PRD §3.4: "from `coverage_start` through `coverage_end`, extended through
    `grace_period_end` when the plan year elects `GRACE_PERIOD`".

    On a GRACE_PERIOD plan year (grace_period_end 2027-03-15), a service_date 2027-02-15 —
    after coverage_end 2026-12-31 but within grace — is accepted (201, SUBMITTED).

    Design: Corner/validations/grace_period_extends_service_window
    """
    set_clock("2027-02-20T00:00:00Z")
    py = create_plan_year(label="PY-GRACE", fsa_relief_mode="GRACE_PERIOD",
                          grace_period_end="2027-03-15")
    p = create_participant(email="gr@x.com")
    acc = create_and_activate_fsa(p["id"], py["id"], account_type="HEALTH_FSA",
                                  elected_amount_cents=100000)
    resp = api.create_claim(
        {"account_id": acc["id"], "service_date": "2027-02-15",
         "expense_category": "MEDICAL", "claimed_amount_cents": 20000,
         "substantiated": True},
        make_participant_headers(p["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SUBMITTED"


def test_duplicate_claim_returns_conflict(api):
    """PRD §3.4: "if another claim on the same account in any status other than `DENIED` or
    `VOIDED` already has the identical `service_date`, `expense_category`, and
    `claimed_amount_cents`, the new claim is rejected with `ERR_DUPLICATE_CLAIM` (HTTP 409)."

    Design: Corner/validations/duplicate_claim_returns_conflict
    """
    py, p, acc = setup_active_fsa(account_type="HEALTH_FSA", elected_amount_cents=100000)
    file_claim(acc["id"], p["id"], service_date="2026-04-01",
               expense_category="MEDICAL", claimed_amount_cents=20000, substantiated=True)
    resp = api.create_claim(
        {"account_id": acc["id"], "service_date": "2026-04-01",
         "expense_category": "MEDICAL", "claimed_amount_cents": 20000,
         "substantiated": True},
        make_participant_headers(p["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM.value)


def test_grace_period_without_grace_end_returns_relief_conflict(api):
    """PRD §3.1: "At creation the server runs a relief-config coherence check: electing
    `GRACE_PERIOD` without a valid `grace_period_end` ... is rejected with
    `ERR_RELIEF_MODE_CONFLICT` (HTTP 422)."

    Design: Corner/validations/relief_mode_conflict_grace_without_grace_end
    """
    payload = create_plan_year_payload(label="PY-BAD", fsa_relief_mode="GRACE_PERIOD")
    resp = api.create_plan_year(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_RELIEF_MODE_CONFLICT.value)
