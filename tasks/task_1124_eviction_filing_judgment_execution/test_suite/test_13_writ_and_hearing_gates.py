"""Writ/hearing gate corners: execute window, unassigned deputy, ops-run
unscheduling, conclude transition, writ window validity, active-writ
uniqueness, hearing uniqueness, hearing window shape, possession gate
(PRD 3.5, 3.7)."""
from test_helpers import (
    ApiErrorId,
    CLERK_A,
    create_hearing_payload,
    create_schedule_lockout_payload,
    create_writ_payload,
    get_case,
    get_hearing,
    get_writ,
    make_deputy_headers,
    make_landlord_headers,
    run_ops,
    schedule_hearing,
    schedule_lockout,
    set_clock,
    setup_case_filed,
    setup_case_hearing_scheduled,
    setup_case_service_complete,
    setup_judgment_final,
    setup_writ_issued,
    setup_writ_scheduled,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from datetime import timedelta
from datetime import datetime


def _plus_seconds(iso_ts, seconds):
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return (dt + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


class TestExecuteBeforeWindowRejected:
    """Corner instance: execute before window_start fails."""

    def test_execute_one_second_before_window_rejected(self, api):
        """PRD 3.7: "The assigned deputy executes while the writ is SCHEDULED
        and the logical clock sits at or after window_start and at or before
        window_end, and not after expires_on; execution outside that envelope
        is rejected with ERR_LOCKOUT_WINDOW_NOT_OPEN (HTTP 409)."

        Design: Corner/state_machines/execute_before_window_rejected
        """
        ctx = setup_writ_scheduled("CA")
        # One second before the window opens.
        set_clock("2026-06-26T08:59:59Z")
        resp = api.execute_writ(ctx["writ"]["id"], {}, make_deputy_headers("dep-1"))
        validate_error(resp, ApiErrorId.ERR_LOCKOUT_WINDOW_NOT_OPEN, 409)
        assert get_writ(ctx["writ"]["id"])["status"] == "SCHEDULED"


class TestExecuteByUnassignedDeputyRejected:
    """Corner instance: only the assigned deputy may execute."""

    def test_other_deputy_rejected(self, api):
        """PRD 2.9: "a lockout execution or cancellation is only accepted
        from the operator whose X-User-ID equals the writ's assigned
        deputy_id (ERR_NOT_ASSIGNED_DEPUTY, HTTP 403)."

        Design: Corner/validations/execute_by_unassigned_deputy_rejected
        """
        ctx = setup_writ_scheduled("CA", deputy_id="dep-1")
        set_clock("2026-06-26T09:00:00Z")  # inside the window
        resp = api.execute_writ(
            ctx["writ"]["id"], {}, make_deputy_headers("dep-9"))
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_DEPUTY, 403)
        assert get_writ(ctx["writ"]["id"])["status"] == "SCHEDULED"


class TestOpsUnschedulesLapsedLockoutWindow:
    """Corner instance: an ops run after window_end (no execution) returns
    the writ to ISSUED and the case to WRIT_ISSUED."""

    def test_lapsed_window_unschedules_not_expires(self, api):
        """PRD 2.5: "fourth, every writ still SCHEDULED whose lockout window
        has closed without execution (the logical clock later than
        window_end) returns to ISSUED with its deputy and window fields
        cleared, and its case returns from LOCKOUT_SCHEDULED to WRIT_ISSUED".

        Design: Corner/state_machines/ops_unschedules_lapsed_lockout_window
        """
        ctx = setup_writ_scheduled("CA")
        # One second past window_end but far inside the writ validity window
        # (expires_on is read from the issued writ).
        expires_on = ctx["writ"]["expires_on"]
        set_clock("2026-06-26T10:00:01Z")
        summary = run_ops()
        assert summary["writs_unscheduled"] == 1
        assert summary["writs_expired"] == 0
        writ = get_writ(ctx["writ"]["id"])
        assert writ["status"] == "ISSUED"
        assert get_case(ctx["case"]["id"])["status"] == "WRIT_ISSUED"


class TestConcludeMarksHearingHeld:
    """Corner instance: conclude moves hearing to HELD and case to
    HEARING_CONCLUDED in one request."""

    def test_conclude_marks_held_and_advances_case(self, api):
        """PRD 3.5: "The hearing becomes HELD and the case advances to
        HEARING_CONCLUDED."

        Design: Corner/state_machines/conclude_marks_hearing_held
        """
        ctx = setup_case_hearing_scheduled("CA")
        hearing = validate_success(api.conclude_hearing(
            ctx["hearing"]["id"], {"notes": "tenant no-show"}, CLERK_A), 200)
        assert hearing["status"] == "HELD"
        assert get_case(ctx["case"]["id"])["status"] == "HEARING_CONCLUDED"


class TestWritWindowMustFitValidity:
    """Corner instance: window_end past expires_on fails."""

    def test_window_end_after_expiry_rejected(self, api):
        """PRD 3.7: "The window must be valid: window_start not in the past,
        window_end later than window_start, and window_end no later than
        expires_on (ERR_WRIT_WINDOW_INVALID, HTTP 422)."

        Design: Corner/validations/writ_window_must_fit_validity
        """
        ctx = setup_writ_issued("CA")
        expires_on = ctx["writ"]["expires_on"]
        # Window ends one second after expires_on (start inside validity).
        resp = api.schedule_lockout(
            ctx["writ"]["id"],
            {"deputy_id": "dep-1",
             "window_start": _plus_seconds(expires_on, -3600),
             "window_end": _plus_seconds(expires_on, 1)},
            make_deputy_headers("dep-1"),
        )
        validate_error(resp, ApiErrorId.ERR_WRIT_WINDOW_INVALID, 422)


class TestSecondActiveWritRejected:
    """Corner instance: one active writ per judgment."""

    def test_second_request_rejected_while_first_active(self, api):
        """PRD 3.7: "no other writ for the same judgment may already be
        active in REQUESTED, ISSUED, or SCHEDULED (ERR_WRIT_ACTIVE_EXISTS,
        HTTP 409)."

        Design: Corner/validations/second_active_writ_rejected
        """
        ctx = setup_judgment_final("CA")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        first = validate_success(api.request_writ(
            ctx["judgment"]["id"], create_writ_payload("CA"), ll), 201)
        assert first["status"] == "REQUESTED"
        resp = api.request_writ(
            ctx["judgment"]["id"], create_writ_payload("CA"), ll)
        validate_error(resp, ApiErrorId.ERR_WRIT_ACTIVE_EXISTS, 409)


class TestWritWithoutPossessionRejected:
    """Corner instance: a money-only judgment cannot support a writ."""

    def test_no_possession_rejected(self, api):
        """PRD 3.7: "the judgment must have granted possession
        (possession_granted true), else ERR_NO_POSSESSION_GRANTED
        (HTTP 422)."

        Design: Corner/validations/writ_without_possession_rejected
        """
        ctx = setup_judgment_final("CA", possession_granted=False)
        ll = make_landlord_headers(ctx["landlord"]["id"])
        resp = api.request_writ(
            ctx["judgment"]["id"], create_writ_payload("CA"), ll)
        validate_error(resp, ApiErrorId.ERR_NO_POSSESSION_GRANTED, 422)


class TestSecondHearingWhileScheduledRejected:
    """Corner instance: at most one SCHEDULED hearing per case."""

    def test_second_hearing_rejected(self, api):
        """PRD 3.5: "The case may hold at most one SCHEDULED hearing at a
        time (ERR_HEARING_ALREADY_SCHEDULED, HTTP 409)."

        Design: Corner/validations/second_hearing_while_scheduled_rejected
        """
        ctx = setup_case_hearing_scheduled("CA")
        resp = api.create_hearing(
            ctx["case"]["id"],
            create_hearing_payload(courtroom="CR-2",
                                   start_at="2026-06-16T10:00:00Z",
                                   end_at="2026-06-16T10:30:00Z"),
            CLERK_A,
        )
        validate_error(resp, ApiErrorId.ERR_HEARING_ALREADY_SCHEDULED, 409)


class TestHearingEndBeforeStartRejected:
    """Corner instance: end_at <= start_at fails the window shape check."""

    def test_end_before_start_rejected(self, api):
        """PRD 3.5: "The window must be well-formed — end_at later than
        start_at (ERR_HEARING_WINDOW_INVALID, HTTP 422)."

        Design: Corner/validations/hearing_end_before_start_rejected
        """
        ctx = setup_case_service_complete("CA")
        resp = api.create_hearing(
            ctx["case"]["id"],
            create_hearing_payload(start_at="2026-06-15T10:00:00Z",
                                   end_at="2026-06-15T09:00:00Z"),
            CLERK_A,
        )
        validate_error(resp, ApiErrorId.ERR_HEARING_WINDOW_INVALID, 422)
