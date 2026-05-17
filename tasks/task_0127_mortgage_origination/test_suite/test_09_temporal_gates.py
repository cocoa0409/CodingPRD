"""TRID waiting period, appraisal-expiry lazy detection, and
rate-lock expiry (PRD §2.9, §3.4, §3.5, §3.6, §3.10)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    create_and_pre_qualify,
    create_and_verify_asset,
    create_and_verify_income,
    iso_plus,
    issue_closing_disclosure,
    issue_loan_estimate,
    order_and_complete_appraisal,
    order_and_complete_title_search,
    place_rate_lock,
    setup_application_ready_for_clear_to_close,
    submit_underwriting,
    submit_underwriting_payload,
    submit_udaap_pass,
    underwrite_approve,
    validate_error,
    validate_success,
)


# ===========================================================================
# TRID 3-business-day waiting period — PRD §3.6, §3.10
# ===========================================================================
def test_trid_waiting_period_before_three_business_days_blocked(
    api, loan_officer_headers,
):
    """PRD §3.6: "For a CLOSING_DISCLOSURE, the system computes
    eligible_to_consummate_at by advancing issued_at forward by exactly
    3 business days."
    PRD §3.10: "SystemClock.now is no earlier than that disclosure's
    eligible_to_consummate_at (the TRID 3-business-day waiting period
    has elapsed)"

    Claim: drive to a CD-issued ACK'd state but DON'T advance the
    clock past the TRID window — clear-to-close returns 409
    ERR_TRID_WAITING_PERIOD.
    """
    _, app, _, _, _ = setup_application_ready_for_clear_to_close(
        clock_anchor="2026-03-02T10:00:00.000Z",
        advance_to_after_trid=False,
    )
    res = api.clear_to_close(app["id"], None, loan_officer_headers)
    validate_error(
        res,
        ApiErrorId.ERR_TRID_WAITING_PERIOD.value,
        expected_status=409,
    )


def test_trid_business_day_skips_weekends_and_holidays(
    api, loan_officer_headers,
):
    """PRD §3.6: "A business day is any day whose weekday is Monday
    through Friday and whose date is not on the static 2026 federal-
    holiday list: New Year's Day (January 1, 2026), Independence Day
    observed (July 6, 2026), and Christmas Day (December 25, 2026).
    Saturdays, Sundays, and listed holidays are skipped without
    consuming a business-day count; only days that are both weekdays
    and non-holidays count. The resulting eligible_to_consummate_at is
    anchored at 00:00:00.000 UTC of the third such business day."

    Claim: a CD issued on 2026-07-02 (Thursday) computes
    eligible_to_consummate_at as:
      day +1 = 2026-07-03 (Fri)  -> count=1
      day +2 = 2026-07-04 (Sat)  -> skip
      day +3 = 2026-07-05 (Sun)  -> skip
      day +4 = 2026-07-06 (Mon, observed Independence Day) -> skip (holiday)
      day +5 = 2026-07-07 (Tue) -> count=2
      day +6 = 2026-07-08 (Wed) -> count=3
    So eligible_to_consummate_at = 2026-07-08T00:00:00.000Z.
    """
    # Set clock to a known Thursday before issuance, then drive the
    # workflow through to CONDITIONAL_APPROVAL so we can issue the CD
    # on the desired date.
    advance_clock("2026-07-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    create_and_verify_income(
        app["id"],
        documented_annual_cents=12_000_000,
        headers=loan_officer_headers,
    )
    create_and_verify_asset(app["id"], headers=loan_officer_headers)
    order_and_complete_appraisal(
        app["id"], appraised_value_cents=40_000_000,
        report_date="2026-07-01T00:00:00.000Z",
        headers=loan_officer_headers,
    )
    order_and_complete_title_search(
        app["id"], defects_found=[], headers=loan_officer_headers,
    )
    issue_loan_estimate(
        app["id"], apr_bps=650, headers=loan_officer_headers,
    )
    submit_underwriting(
        app["id"], headers=loan_officer_headers,
    )
    submit_udaap_pass(app["id"])
    underwrite_approve(app["id"], headers=loan_officer_headers)
    place_rate_lock(
        app["id"], locked_rate_bps=650, headers=loan_officer_headers,
    )
    cd = issue_closing_disclosure(
        app["id"], apr_bps=650, headers=loan_officer_headers,
    )
    expected = "2026-07-08T00:00:00.000Z"
    assert cd["eligible_to_consummate_at"] == expected, (
        "PRD §3.6: CD issued on 2026-07-02 must skip Sat/Sun and the "
        "observed July 6 holiday; eligible_to_consummate_at must be "
        f"2026-07-08T00:00:00.000Z. Got {cd['eligible_to_consummate_at']}."
    )


# ===========================================================================
# Appraisal expiry — PRD §3.4
# ===========================================================================
def test_appraisal_lazy_expiry_at_submit_underwriting(
    api, loan_officer_headers,
):
    """PRD §3.4: "If the system observes during a downstream state-
    advancing operation that an appraisal's valid_until has elapsed
    (SystemClock.now is strictly greater than valid_until), it lazily
    transitions the appraisal from COMPLETED to EXPIRED — and surfaces
    ERR_APPRAISAL_EXPIRED to the caller of that operation."

    Claim: with report_date=2026-01-01 the appraisal valid_until is
    2026-05-01 at 23:59:59.999 UTC. Advance the clock to
    2026-05-02T00:00:00 (strictly greater than valid_until) and attempt
    submit-underwriting. The request must surface ERR_APPRAISAL_EXPIRED.
    """
    advance_clock("2026-01-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    create_and_verify_income(
        app["id"],
        documented_annual_cents=12_000_000,
        headers=loan_officer_headers,
    )
    create_and_verify_asset(app["id"], headers=loan_officer_headers)
    order_and_complete_appraisal(
        app["id"], appraised_value_cents=40_000_000,
        report_date="2026-01-01T00:00:00.000Z",
        headers=loan_officer_headers,
    )
    order_and_complete_title_search(
        app["id"], defects_found=[], headers=loan_officer_headers,
    )
    issue_loan_estimate(
        app["id"], apr_bps=650, headers=loan_officer_headers,
    )
    # Advance to just past valid_until (2026-05-01T23:59:59.999Z).
    advance_clock("2026-05-02T00:00:01.000Z")
    res = api.submit_underwriting(
        app["id"],
        submit_underwriting_payload(compliance_reviewer_id="co-001"),
        loan_officer_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_APPRAISAL_EXPIRED.value,
        expected_status=409,
    )


def test_appraisal_valid_at_inclusive_boundary(api, loan_officer_headers):
    """PRD §3.4: "The appraisal is considered valid for use as long as
    SystemClock.now is no later than valid_until (the boundary is
    inclusive)."

    Claim: at SystemClock.now == valid_until, the appraisal is still
    valid; submit-underwriting succeeds.
    """
    advance_clock("2026-01-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    create_and_verify_income(
        app["id"],
        documented_annual_cents=12_000_000,
        headers=loan_officer_headers,
    )
    create_and_verify_asset(app["id"], headers=loan_officer_headers)
    appr = order_and_complete_appraisal(
        app["id"], appraised_value_cents=40_000_000,
        report_date="2026-01-01T00:00:00.000Z",
        headers=loan_officer_headers,
    )
    order_and_complete_title_search(
        app["id"], defects_found=[], headers=loan_officer_headers,
    )
    issue_loan_estimate(
        app["id"], apr_bps=650, headers=loan_officer_headers,
    )
    # Advance to exactly the inclusive boundary.
    advance_clock(appr["valid_until"])
    res = api.submit_underwriting(
        app["id"],
        submit_underwriting_payload(compliance_reviewer_id="co-001"),
        loan_officer_headers,
    )
    out = validate_success(res, 200)
    assert out["status"] == "UNDERWRITING"


# ===========================================================================
# Rate lock expiry — PRD §3.5, §3.10
# ===========================================================================
def test_close_after_rate_lock_expired_rejected(api, loan_officer_headers):
    """PRD §3.10: "Closing the application transitions status from
    CLEAR_TO_CLOSE to CLOSED. The only precondition specific to this
    step is that SystemClock.now must still be no later than
    RateLock.lock_expires_at — if the lock has aged out since
    clear-to-close was issued, the close is rejected with
    ERR_RATE_LOCK_EXPIRED and a fresh extension is required."

    Claim: after a successful clear-to-close, advance the clock past
    RateLock.lock_expires_at; the subsequent close returns
    ERR_RATE_LOCK_EXPIRED.
    """
    _, app, _, _, _ = setup_application_ready_for_clear_to_close(
        clock_anchor="2026-03-02T10:00:00.000Z",
    )
    validate_success(api.clear_to_close(
        app["id"], None, loan_officer_headers,
    ), 200)
    rl = validate_success(api.get_rate_lock(
        app["id"], loan_officer_headers,
    ), 200)
    advance_clock(iso_plus(rl["lock_expires_at"], seconds=1))
    res = api.close_application(app["id"], None, loan_officer_headers)
    validate_error(
        res,
        ApiErrorId.ERR_RATE_LOCK_EXPIRED.value,
        expected_status=409,
    )


def test_clock_advance_admin_only(api, loan_officer_headers):
    """PRD §4: "POST /_clock/advance — Admin only".

    Claim: a LoanOfficer attempting to advance the clock is rejected
    with ERR_FORBIDDEN_ROLE.
    """
    res = api.advance_clock(
        {"to": "2026-04-01T00:00:00.000Z"}, loan_officer_headers,
    )
    validate_error(
        res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403,
    )


def test_clock_get_returns_current_now(api, admin_headers):
    """PRD §2.9: "a public read endpoint exposes the current now."
    PRD §4: GET /_clock is readable by Admin/LoanOfficer/etc.

    Claim: after /_clock/advance, GET /_clock returns the advanced
    value.
    """
    advance_clock("2026-04-15T12:34:56.789Z")
    res = api.get_clock(admin_headers)
    out = validate_success(res, 200)
    assert out.get("now") == "2026-04-15T12:34:56.789Z", (
        f"PRD §2.9: SystemClock.now must reflect the last /_clock/"
        f"advance. Got {out.get('now')}."
    )
