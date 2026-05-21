"""DailyLog certification and edit-window — PRD §3.7."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_days,
    add_seconds,
    advance_clock_to_iso,
    assert_daily_log,
    assert_integrity_hash_format,
    certify_log,
    edit_duty_event,
    find_log_for_date,
    get_daily_log,
    list_daily_logs,
    make_driver_headers,
    post_duty_event,
    setup_certified_log,
    setup_log_at_midnight_boundary,
    validate_error,
    validate_success,
)


# ===========================================================================
# Successful certify — PRD §3.7
# ===========================================================================
class TestCertifySuccess:

    def test_certify_sets_status_and_count_and_hash(self, api):
        """PRD §3.7: "On a successful certify, `DailyLog.status` is
        set to `CERTIFIED`, `certified_at` is set to the server clock
        at the moment of certification, `certification_count` is set
        to 1, and `integrity_hash` is recomputed and frozen against
        the canonical projection described below."

        Claim: after certify, DailyLog has status=="CERTIFIED",
        certification_count==1, certified_at is non-null and ISO
        8601, and integrity_hash is a 64-char lowercase hex string.
        """
        state = setup_certified_log(log_date="2026-07-20")
        log = state["log"]
        assert log["status"] == "CERTIFIED"
        assert log["certification_count"] == 1
        assert log["certified_at"] is not None
        assert_integrity_hash_format(log["integrity_hash"])
        assert_daily_log(log)


# ===========================================================================
# Certify rejected when log_date == today — PRD §3.7
# ===========================================================================
class TestCertifyBoundary:

    def test_certify_today_rejected(self, api):
        """PRD §3.7: "The transition from `UNCERTIFIED` to
        `CERTIFIED` requires the log's `log_date` to be strictly
        earlier than today as measured in the driver's
        `home_terminal_timezone`; certifying a log whose date is
        today or in the future is rejected with
        `ERR_LOG_NOT_YET_CERTIFIABLE`."

        Claim: when log_date equals today in the driver's
        home_terminal_timezone, certify is rejected with
        ERR_LOG_NOT_YET_CERTIFIABLE at HTTP 422 (boundary at
        log_date == today).
        """
        state = setup_log_at_midnight_boundary(
            log_date="2026-07-25",
            home_terminal_timezone="UTC",
        )
        driver, log = state["driver"], state["log"]
        resp = api.certify_daily_log(
            driver["id"], log["id"], make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LOG_NOT_YET_CERTIFIABLE.value)

    def test_certify_after_midnight_succeeds(self, api):
        """PRD §3.7: "The transition from `UNCERTIFIED` to
        `CERTIFIED` requires the log's `log_date` to be strictly
        earlier than today as measured in the driver's
        `home_terminal_timezone`".

        Claim: after the server clock advances past local midnight
        (so log_date < today), certify succeeds.
        """
        state = setup_log_at_midnight_boundary(
            log_date="2026-07-26",
            home_terminal_timezone="UTC",
        )
        driver, log = state["driver"], state["log"]
        # Advance to next day.
        advance_clock_to_iso("2026-07-27T00:00:00.000Z")
        resp = api.certify_daily_log(
            driver["id"], log["id"], make_driver_headers(driver["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CERTIFIED"


# ===========================================================================
# Append on CERTIFIED log rejected — PRD §3.3
# ===========================================================================
class TestAppendOnCertifiedLog:

    def test_append_event_on_certified_log_date_rejected(self, api):
        """PRD §3.3: "A duty event whose `event_time` falls on a
        calendar date whose `DailyLog.status` is `CERTIFIED` or
        `RECERTIFIED` cannot be appended directly and is rejected with
        `ERR_LOG_ALREADY_CERTIFIED`".

        Claim: posting a DutyEvent with event_time on a log_date
        whose DailyLog.status is CERTIFIED returns
        ERR_LOG_ALREADY_CERTIFIED.
        """
        from test_helpers import create_duty_event_payload
        state = setup_certified_log(log_date="2026-07-28")
        driver, vehicle, log = state["driver"], state["vehicle"], state["log"]
        # Attempt to post a new event on 2026-07-28T23:00:00 — same
        # calendar date as the certified log.
        payload = create_duty_event_payload(
            new_status="ON_DUTY_NOT_DRIVING",
            event_time="2026-07-28T23:00:00.000Z",
            vehicle_id=vehicle["id"],
            odometer_miles=2000.0,
            annotation="Forgotten post-trip inspection note.",
        )
        resp = api.create_duty_event(
            driver["id"], payload, make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LOG_ALREADY_CERTIFIED.value)


# ===========================================================================
# Edit window — PRD §3.7
# ===========================================================================
class TestEditWindow:

    def test_edit_within_8_day_window_succeeds(self, api):
        """PRD §3.7: "the server clock to be strictly less than
        `event_time` plus eight days - the FMCSA edit window; an
        edit submitted after that window is rejected with
        `ERR_EDIT_WINDOW_EXPIRED`."

        Claim: an edit to a DutyEvent submitted within 8 days of the
        event's event_time succeeds and creates a new ACTIVE event.
        """
        state = setup_certified_log(log_date="2026-08-01")
        driver = state["driver"]
        events = state["events"]
        # Edit the first event (ON_DUTY_NOT_DRIVING) within the
        # window — clock is currently next day after log_date.
        edited = edit_duty_event(
            driver, events[0]["id"],
            annotation="Corrected pre-trip annotation v2.",
        )
        assert edited["edit_state"] == "ACTIVE"

    def test_edit_after_8_day_window_rejected(self, api):
        """PRD §3.7: "the server clock to be strictly less than
        `event_time` plus eight days ... an edit submitted after
        that window is rejected with `ERR_EDIT_WINDOW_EXPIRED`."

        Claim: an edit submitted strictly more than 8 days after the
        event's event_time fails with ERR_EDIT_WINDOW_EXPIRED.
        """
        from test_helpers import edit_duty_event_payload
        state = setup_certified_log(log_date="2026-08-10")
        driver = state["driver"]
        events = state["events"]
        first_event_time = events[0]["event_time"]
        # Advance the clock to event_time + 8 days + 1 hour.
        beyond = add_seconds(add_days(first_event_time, 8), 3600)
        advance_clock_to_iso(beyond)
        payload = edit_duty_event_payload(
            annotation="Late correction outside the edit window.",
        )
        resp = api.edit_duty_event(
            driver["id"], events[0]["id"], payload,
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EDIT_WINDOW_EXPIRED.value)
