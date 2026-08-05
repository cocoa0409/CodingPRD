"""Claim assembly and adjudication: round-then-sum totals, the denied/rebill
cycle, submittability precedence over timely filing, the timely-filing day
boundary, and the encounter/attach/listing corners.
"""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated, get_success_data,
    setup_billing_context, create_verified_log, create_logged_log,
    create_draft_claim, attach_log, setup_claim_with_verified_log,
    submit_claim, approve_claim, deny_claim, set_clock,
    create_student,
    api_client,
)

MC = TEST_USERS["medicaid_coordinator_headers"]
BC = TEST_USERS["billing_coordinator_headers"]
SR = TEST_USERS["state_reviewer_headers"]

_WINDOW_2025 = {"effective_date": "2025-01-01", "expiration_date": "2026-12-31"}


# --- combinatorial_formula / claim_total_per_log_rounding_then_sum -----------
def _two_eight_minute_logs_claim():
    ctx = setup_billing_context()
    log1 = create_verified_log(ctx["authorization"]["id"], ctx["provider"]["id"], ctx["student"]["id"],
                               start_time="2026-03-01T09:00:00Z", end_time="2026-03-01T09:08:00Z",
                               delivered_minutes=8, note="n1")
    log2 = create_verified_log(ctx["authorization"]["id"], ctx["provider"]["id"], ctx["student"]["id"],
                               start_time="2026-03-01T10:00:00Z", end_time="2026-03-01T10:08:00Z",
                               delivered_minutes=8, note="n2")
    claim = create_draft_claim(ctx["student"]["id"])
    attach_log(claim["id"], log1["id"])
    claim = attach_log(claim["id"], log2["id"])
    return log1, log2, claim


def test_claim_total_is_per_log_round_then_sum(api):
    """PRD §3.5: "That sum is computed by rounding each log individually first: for
    every attached log, divide its delivered_minutes by its authorization's
    unit_minutes and round half-up to whole units, multiply by that
    authorization's unit_rate_cents to get the log's charge in cents, and only
    then add the per-log charges together."

    Design: Difficulty/combinatorial_formula/claim_total_per_log_rounding_then_sum
    """
    _log1, _log2, claim = _two_eight_minute_logs_claim()
    assert claim["total_charge_cents"] == 6000
    assert claim["attached_log_count"] == 2


def test_each_short_log_rounds_up_to_one_unit(api):
    """PRD §3.5: "The rounding is done per log before summing — the system never
    sums delivered minutes across logs and rounds once at the end."

    Design: Difficulty/combinatorial_formula/claim_total_per_log_rounding_then_sum
    """
    log1, log2, _claim = _two_eight_minute_logs_claim()
    assert get_success_data(api.get_service_log(log1["id"], MC))["delivered_units"] == 1
    assert get_success_data(api.get_service_log(log2["id"], MC))["delivered_units"] == 1


# --- non_linear_state_machine / claim_denied_rebill_cycle --------------------
def _rebilled_then_paid_claim():
    ctx = setup_claim_with_verified_log()
    claim_id = ctx["claim"]["id"]
    submit_claim(claim_id)
    deny_claim(claim_id, denial_reason="DOC_INCOMPLETE")
    submit_claim(claim_id)          # rebill
    approve_claim(claim_id)
    return ctx


def test_rebilled_claim_reaches_paid_with_incremented_rebill_count(api):
    """PRD §3.6: "Rebilling is the same submit action applied to a claim in status
    DENIED: it advances the claim back to SUBMITTED, increments rebill_count by
    one, re-stamps submitted_date, clears denial_reason back to null, and moves
    every attached log from DENIED back to CLAIMED."

    Design: Difficulty/non_linear_state_machine/claim_denied_rebill_cycle
    """
    ctx = _rebilled_then_paid_claim()
    claim = get_success_data(api.get_claim(ctx["claim"]["id"], MC))
    assert claim["status"] == "PAID"
    assert claim["rebill_count"] == 1


def test_rebilled_claim_clears_denial_and_pays_logs(api):
    """PRD §3.5: "On APPROVE, the claim moves to PAID ... and every attached log
    advances from CLAIMED to PAID."

    Design: Difficulty/non_linear_state_machine/claim_denied_rebill_cycle
    """
    ctx = _rebilled_then_paid_claim()
    claim = get_success_data(api.get_claim(ctx["claim"]["id"], MC))
    assert claim["denial_reason"] is None
    assert get_success_data(api.get_service_log(ctx["log"]["id"], MC))["status"] == "PAID"


# --- priority_pair_validation_conflict / claim_submit_state_beats_timely -----
def _paid_claim_then_stale_clock():
    ctx = setup_claim_with_verified_log(
        clock="2025-02-01T00:00:00Z", service_date="2025-01-01",
        start_time="2025-01-01T09:00:00Z", end_time="2025-01-01T09:40:00Z",
        service_month="2025-01", cred_overrides=dict(_WINDOW_2025), auth_overrides=dict(_WINDOW_2025))
    submit_claim(ctx["claim"]["id"])
    approve_claim(ctx["claim"]["id"])
    set_clock("2026-06-01T00:00:00Z")   # now also > 365 days since service
    return ctx


def test_submit_on_paid_claim_returns_not_submittable_over_timely(api):
    """PRD §3.5: "A submit is only admissible when the claim's status is DRAFT or
    DENIED; a submit against any other status is rejected with
    ERR_CLAIM_NOT_SUBMITTABLE (HTTP 409)."
    PRD §2.5: "When more than one validation could fire on a single request, the
    system evaluates them in a fixed precedence so the returned error_id is
    deterministic."

    Design: Difficulty/priority_pair_validation_conflict/claim_submit_state_beats_timely_filing
    """
    ctx = _paid_claim_then_stale_clock()
    resp = api.submit_claim(ctx["claim"]["id"], BC)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SUBMITTABLE)


def test_paid_claim_state_unchanged_after_rejected_resubmit(api):
    """PRD §3.5: "A submit is only admissible when the claim's status is DRAFT or
    DENIED; a submit against any other status is rejected with
    ERR_CLAIM_NOT_SUBMITTABLE (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/claim_submit_state_beats_timely_filing
    """
    ctx = _paid_claim_then_stale_clock()
    api.submit_claim(ctx["claim"]["id"], BC)
    assert get_success_data(api.get_claim(ctx["claim"]["id"], MC))["status"] == "PAID"


# --- boundary_precision_check / claim_timely_filing_day_boundary -------------
def _draft_claim_dated_2025_01_01():
    ctx = setup_claim_with_verified_log(
        clock="2025-02-01T00:00:00Z", service_date="2025-01-01",
        start_time="2025-01-01T09:00:00Z", end_time="2025-01-01T09:40:00Z",
        service_month="2025-01", cred_overrides=dict(_WINDOW_2025), auth_overrides=dict(_WINDOW_2025))
    return ctx


def test_timely_filing_366_days_rejected(api):
    """PRD §3.5: "A difference of exactly 365 days still files successfully, and
    366 days fails, at which point the submit is rejected with
    ERR_TIMELY_FILING_EXCEEDED (HTTP 422)."

    Design: Difficulty/boundary_precision_check/claim_timely_filing_day_boundary
    """
    ctx = _draft_claim_dated_2025_01_01()
    set_clock("2026-01-02T00:00:00Z")   # 366 days after 2025-01-01
    resp = api.submit_claim(ctx["claim"]["id"], BC)
    validate_error(resp, ApiErrorId.ERR_TIMELY_FILING_EXCEEDED)
    assert get_success_data(api.get_claim(ctx["claim"]["id"], MC))["status"] == "DRAFT"


def test_timely_filing_365_days_accepted(api):
    """PRD §3.5: "Timely filing compares the current clock date against the latest
    service_date among the attached logs: the difference must be at most 365 days.
    A difference of exactly 365 days still files successfully, and 366 days fails".

    Design: Difficulty/boundary_precision_check/claim_timely_filing_day_boundary
    """
    ctx = _draft_claim_dated_2025_01_01()
    set_clock("2026-01-01T00:00:00Z")   # 365 days after 2025-01-01
    submitted = validate_success(api.submit_claim(ctx["claim"]["id"], BC))
    assert submitted["status"] == "SUBMITTED"


# --- validations / endpoints corners -----------------------------------------
def test_claim_submit_with_no_encounters_returns_error(api):
    """PRD §3.5: "the claim must have at least one attached encounter
    (attached_log_count of at least 1), else ERR_CLAIM_NO_ENCOUNTERS (HTTP 422)".

    Design: Corner/validations/claim_submit_with_no_encounters_returns_error
    """
    set_clock("2026-03-15T00:00:00Z")
    student = create_student()
    claim = create_draft_claim(student["id"])
    resp = api.submit_claim(claim["id"], BC)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NO_ENCOUNTERS)
    assert get_success_data(api.get_claim(claim["id"], MC))["status"] == "DRAFT"


def test_attach_non_verified_log_returns_error(api):
    """PRD §3.5: "Attaching advances that log from VERIFIED to CLAIMED, but only
    when the log is VERIFIED and unattached; an attach against a log that is not
    verified-and-unattached is rejected with ERR_LOG_NOT_BILLABLE (HTTP 409)."

    Design: Corner/endpoints/attach_non_verified_log_returns_error
    """
    ctx = setup_billing_context()
    log = create_logged_log(ctx["authorization"]["id"], ctx["provider"]["id"], ctx["student"]["id"])
    claim = create_draft_claim(ctx["student"]["id"])
    resp = api.attach_log(claim["id"], {"service_log_id": log["id"]}, BC)
    validate_error(resp, ApiErrorId.ERR_LOG_NOT_BILLABLE)
    assert get_success_data(api.get_claim(claim["id"], MC))["attached_log_count"] == 0


def test_claims_list_pagination_shape(api):
    """PRD §2.3: "The meta block of a list response carries limit, offset,
    total_count (the full count of matching resources before the page window), and
    has_more (true when unreturned rows remain beyond the current window)."

    Design: Corner/endpoints/claims_list_pagination_shape
    """
    student = create_student()
    create_draft_claim(student["id"], service_month="2026-01")
    create_draft_claim(student["id"], service_month="2026-02")
    data, meta = validate_paginated(api.list_claims(BC, params={"student_id": student["id"], "limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
