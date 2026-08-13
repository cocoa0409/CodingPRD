"""Clinic session lifecycle: open/close/cancel transitions, cascades, spacing rule."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_clinic_session,
    book_appointment,
    create_clinic_session_payload,
    create_open_session,
    create_student,
    get_session,
    validate_error,
    validate_success,
)


class TestSessionLifecycleTransitions:

    def test_open_twice_rejected(self, nurse_headers):
        """PRD section 2.7: "opening a session requires `SCHEDULED`
        (`ERR_SESSION_NOT_OPENABLE`), closing requires `OPEN`
        (`ERR_SESSION_NOT_CLOSABLE`), cancelling requires `SCHEDULED` or `OPEN`
        (`ERR_SESSION_NOT_CANCELLABLE`), and booking requires `OPEN`
        (`ERR_SESSION_NOT_OPEN`)".
        PRD section 3.7: "A session is born `SCHEDULED` with `booked_count` 0; the
        nurse then opens it (`SCHEDULED` → `OPEN`) to accept bookings, closes it
        (`OPEN` → `CLOSED`) when done, or cancels it from either `SCHEDULED` or
        `OPEN`."

        Design: Corner/state_machines/open_twice_rejected
        """
        session = create_open_session("SCH-C11")
        assert session["status"] == "OPEN"
        resp = api_client.open_clinic_session(session["id"], nurse_headers)
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_OPENABLE)

    def test_close_from_scheduled_rejected(self, nurse_headers):
        """PRD section 2.7: "opening a session requires `SCHEDULED`
        (`ERR_SESSION_NOT_OPENABLE`), closing requires `OPEN`
        (`ERR_SESSION_NOT_CLOSABLE`), cancelling requires `SCHEDULED` or `OPEN`
        (`ERR_SESSION_NOT_CANCELLABLE`), and booking requires `OPEN`
        (`ERR_SESSION_NOT_OPEN`)".

        Design: Corner/state_machines/close_from_scheduled_rejected
        """
        created = validate_success(
            api_client.create_clinic_session(
                create_clinic_session_payload(school_code="SCH-C12"), nurse_headers
            ),
            201,
        )
        assert created["status"] == "SCHEDULED"
        resp = api_client.close_clinic_session(created["id"], nurse_headers)
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_CLOSABLE)

    def test_cancel_closed_session_rejected(self, nurse_headers):
        """PRD section 2.7: "opening a session requires `SCHEDULED`
        (`ERR_SESSION_NOT_OPENABLE`), closing requires `OPEN`
        (`ERR_SESSION_NOT_CLOSABLE`), cancelling requires `SCHEDULED` or `OPEN`
        (`ERR_SESSION_NOT_CANCELLABLE`), and booking requires `OPEN`
        (`ERR_SESSION_NOT_OPEN`)".

        Design: Corner/state_machines/cancel_closed_session_rejected
        """
        session = create_open_session("SCH-C13")
        closed = validate_success(
            api_client.close_clinic_session(session["id"], nurse_headers), 200
        )
        assert closed["status"] == "CLOSED"
        resp = api_client.cancel_clinic_session(session["id"], nurse_headers)
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_CANCELLABLE)

    def test_cancel_session_cascades_to_appointments(self, nurse_headers):
        """PRD section 3.7: "Cancelling a session cascades: every appointment still
        `BOOKED` transitions to `CANCELLED` and the session's `booked_count` is
        recomputed."

        Design: Corner/state_machines/cancel_session_cascades_to_appointments
        """
        student = create_student("SCH-Y", legal_name="Cas Cade")
        session = create_open_session("SCH-C7",
                                      session_date="2026-08-10T09:00:00Z")
        appointment = book_appointment(session["id"], student["id"],
                                       start_time="2026-08-10T09:30:00Z",
                                       end_time="2026-08-10T10:00:00Z")
        assert get_session(session["id"])["booked_count"] == 1

        cancelled = validate_success(
            api_client.cancel_clinic_session(session["id"], nurse_headers), 200
        )
        assert_clinic_session(cancelled)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["booked_count"] == 0

        appt_after = validate_success(
            api_client.get_appointment(appointment["id"], nurse_headers), 200
        )
        assert appt_after["status"] == "CANCELLED"


class TestSessionSpacingRule:

    def test_session_gap_four_days_rejected(self, nurse_headers):
        """PRD section 3.7: "Sessions of the same school must be spaced out: no new
        session may begin less than 7 days from an existing session of that school
        in `SCHEDULED`, `OPEN`, or `CLOSED` status — a gap of exactly 7 days is
        allowed, and `CANCELLED` sessions are ignored by this check. A too-close
        session is rejected with `ERR_SESSION_GAP_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/session_minimum_gap_buffer
        """
        validate_success(
            api_client.create_clinic_session(
                create_clinic_session_payload(
                    school_code="SCH-C4",
                    session_date="2026-09-01T09:00:00Z",
                ),
                nurse_headers,
            ),
            201,
        )
        # 2026-09-05 is 4 days after 2026-09-01: less than the 7-day minimum.
        resp = api_client.create_clinic_session(
            create_clinic_session_payload(
                school_code="SCH-C4", session_date="2026-09-05T09:00:00Z"
            ),
            nurse_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_GAP_VIOLATION)

    def test_session_gap_exactly_seven_days_allowed(self, nurse_headers):
        """PRD section 3.7: "Sessions of the same school must be spaced out: no new
        session may begin less than 7 days from an existing session of that school
        in `SCHEDULED`, `OPEN`, or `CLOSED` status — a gap of exactly 7 days is
        allowed, and `CANCELLED` sessions are ignored by this check. A too-close
        session is rejected with `ERR_SESSION_GAP_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/session_minimum_gap_buffer
        """
        validate_success(
            api_client.create_clinic_session(
                create_clinic_session_payload(
                    school_code="SCH-C4",
                    session_date="2026-09-01T09:00:00Z",
                ),
                nurse_headers,
            ),
            201,
        )
        # 2026-09-08 is exactly 7 days after 2026-09-01: allowed.
        created = validate_success(
            api_client.create_clinic_session(
                create_clinic_session_payload(
                    school_code="SCH-C4", session_date="2026-09-08T09:00:00Z"
                ),
                nurse_headers,
            ),
            201,
        )
        assert_clinic_session(created)
        assert created["status"] == "SCHEDULED"
