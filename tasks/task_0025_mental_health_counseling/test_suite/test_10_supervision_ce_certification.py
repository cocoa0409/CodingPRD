"""Supervision sessions, continuing-education records, and certification
cycles (PRD §3.2, §3.10).

Several supervision/CE tests are guarded behind preconditions that require
an ACTIVE counselor; we use the bring_counselor_to_active helper which
relies on the implementer's permissive cycle-1 path. The difficulty-design
file exercises the strict eligibility-gated path."""
from __future__ import annotations
import pytest

from test_helpers import (
    advance_clock,
    api_client,
    assert_supervision_session,
    bring_counselor_to_active,
    confirm_appointment,
    create_appointment_in_hold,
    create_ce_record_payload,
    create_client,
    create_counseling_record,
    create_counselor,
    create_slot,
    create_supervision_session_payload,
    DEFAULT_T0,
    fetch_open_cycle_for,
    make_admin_headers,
    make_client_headers,
    make_counselor_headers,
    make_supervisor_headers,
    setup_counselor_and_completed_client,
    shift,
    start_appointment,
    validate_error,
    validate_success,
)


def _completed_appointment_for_counselor(counselor, client_completed):
    """Walk a STANDARD appointment to COMPLETED state for use as a
    case_appointment_id."""
    slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=400))
    appt = create_appointment_in_hold(
        counselor=counselor, client=client_completed, slot=slot,
        appointment_type="STANDARD", payment_mode="PAY_PER_SESSION",
    )
    confirmed = confirm_appointment(client_completed, appt)
    advance_clock(shift(slot["start_at"], minutes=-4))
    started = start_appointment(counselor, confirmed)
    create_counseling_record(
        counselor=counselor, appointment=started,
        encrypted_note_blob="aGVsbG8td29ybGQ=",
    )
    res = api_client.complete_appointment(
        started["id"], make_counselor_headers(counselor["id"]),
    )
    return validate_success(res, expected_status=200)


class TestSupervisionEligibility:
    def test_self_supervise_rejected(self, api):
        """PRD §3.10: "the supervisor's `id` must not equal the supervisee's
        `id` ... otherwise `ERR_SUPERVISOR_INELIGIBLE`."
        """
        counselor, client = setup_counselor_and_completed_client()
        completed = _completed_appointment_for_counselor(counselor, client)
        # Self-supervise: counselor_id == supervisor_id.
        payload = create_supervision_session_payload(
            counselor_id=counselor["id"],
            supervisor_id=counselor["id"],   # self
            case_appointment_id=completed["id"],
            scheduled_at=shift(DEFAULT_T0, hours=500),
            duration_hours=1.0,
        )
        res = api.create_supervision_session(
            payload, make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_SUPERVISOR_INELIGIBLE", expected_status=422)

    def test_specialty_mismatch_rejected(self, api):
        """PRD §3.10: "and the supervisor's `specialty_tags` must overlap
        the supervisee's `specialty_tags`; otherwise `ERR_SUPERVISOR_INELIGIBLE`."
        """
        counselor, client = setup_counselor_and_completed_client()
        completed = _completed_appointment_for_counselor(counselor, client)
        # Create a supervisor with non-overlapping specialty tags.
        supervisor = create_counselor(specialty_tags=["FAMILY", "ADDICTION"])
        # Counselor (default specialty_tags=[ANXIETY, DEPRESSION]) has no
        # overlap with [FAMILY, ADDICTION].
        payload = create_supervision_session_payload(
            counselor_id=counselor["id"],
            supervisor_id=supervisor["id"],
            case_appointment_id=completed["id"],
            scheduled_at=shift(DEFAULT_T0, hours=500),
            duration_hours=1.0,
        )
        res = api.create_supervision_session(
            payload, make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_SUPERVISOR_INELIGIBLE", expected_status=422)


class TestSupervisionCaseValidity:
    def test_non_completed_case_rejected(self, api):
        """PRD §3.10: "`case_appointment_id` (the appointment under
        discussion, which must already be `COMPLETED` and must be the
        supervisee's own — otherwise `ERR_INVALID_CASE`)..."
        """
        counselor, client = setup_counselor_and_completed_client()
        # Create a CONFIRMED (not COMPLETED) appointment as the case.
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=400))
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="STANDARD", payment_mode="PAY_PER_SESSION",
        )
        confirmed = confirm_appointment(client, appt)   # CONFIRMED, not COMPLETED
        # Need a supervisor with overlapping specialty tags.
        supervisor = create_counselor(
            specialty_tags=["ANXIETY", "DEPRESSION", "TRAUMA"],
        )
        payload = create_supervision_session_payload(
            counselor_id=counselor["id"],
            supervisor_id=supervisor["id"],
            case_appointment_id=confirmed["id"],
            scheduled_at=shift(DEFAULT_T0, hours=500),
            duration_hours=1.0,
        )
        res = api.create_supervision_session(
            payload, make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_INVALID_CASE", expected_status=422)


class TestSupervisionApproval:
    def test_approve_with_correct_supervisor_succeeds(self, api):
        """PRD §3.10: "Approval is permitted only while `status` is
        `PENDING_REVIEW`, only when `X-User-ID` equals `supervisor_id`, and
        only when the request body carries an `evaluation_score` between 1
        and 5 inclusive. On approval the row's `status` becomes `APPROVED`,
        and the counselor's `total_supervision_hours` is incremented by
        `duration_hours`..."
        """
        counselor, client = setup_counselor_and_completed_client()
        completed = _completed_appointment_for_counselor(counselor, client)
        supervisor = create_counselor(
            specialty_tags=["ANXIETY", "DEPRESSION", "TRAUMA"],
        )
        payload = create_supervision_session_payload(
            counselor_id=counselor["id"],
            supervisor_id=supervisor["id"],
            case_appointment_id=completed["id"],
            scheduled_at=shift(DEFAULT_T0, hours=500),
            duration_hours=1.0,
        )
        res = api.create_supervision_session(
            payload, make_counselor_headers(counselor["id"]),
        )
        session = validate_success(res, expected_status=201)
        # Approve as the supervisor (not as admin or counselor).
        approve_res = api.approve_supervision_session(
            session["id"], {"evaluation_score": 4},
            make_supervisor_headers(supervisor["id"]),
        )
        approved = validate_success(approve_res, expected_status=200)
        assert approved["status"] == "APPROVED"
        assert approved["evaluation_score"] == 4

    def test_approve_with_wrong_supervisor_rejected(self, api):
        """PRD §3.10: "Approval is permitted only while `status` is
        `PENDING_REVIEW`, only when `X-User-ID` equals `supervisor_id`..."
        """
        counselor, client = setup_counselor_and_completed_client()
        completed = _completed_appointment_for_counselor(counselor, client)
        supervisor_a = create_counselor(
            specialty_tags=["ANXIETY", "DEPRESSION", "TRAUMA"],
        )
        supervisor_b = create_counselor(
            specialty_tags=["ANXIETY", "DEPRESSION", "TRAUMA"],
        )
        payload = create_supervision_session_payload(
            counselor_id=counselor["id"],
            supervisor_id=supervisor_a["id"],
            case_appointment_id=completed["id"],
            scheduled_at=shift(DEFAULT_T0, hours=500),
            duration_hours=1.0,
        )
        session = validate_success(
            api.create_supervision_session(
                payload, make_counselor_headers(counselor["id"]),
            ),
            expected_status=201,
        )
        # Attempt approval as supervisor_b, who is NOT the
        # supervision_session.supervisor_id.
        res = api.approve_supervision_session(
            session["id"], {"evaluation_score": 4},
            make_supervisor_headers(supervisor_b["id"]),
        )
        # PRD §2.1 ownership check fires before the state check; result is
        # ERR_FORBIDDEN. Some implementers may surface ERR_INVALID_STATE
        # since the SupervisionSession is in PENDING_REVIEW but the actor
        # is wrong — both are rooted in PRD prose.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(res, ["ERR_FORBIDDEN", "ERR_INVALID_STATE"])


class TestCERecord:
    def test_create_ce_record_starts_pending_review(self, api):
        """PRD §3.10: "A counselor submits a ContinuingEducationRecord
        carrying `counselor_id`, `course_title`, `completed_at`, and
        `hours_claimed` (greater than zero and at most 40). At creation
        `status` is `PENDING_REVIEW`, `hours_credited` is zero."
        """
        counselor = create_counselor()
        res = api.create_ce_record(
            create_ce_record_payload(
                counselor_id=counselor["id"],
                course_title="Mental Health Best Practices",
                completed_at="2026-04-01T00:00:00.000Z",
                hours_claimed=10.0,
            ),
            make_counselor_headers(counselor["id"]),
        )
        record = validate_success(res, expected_status=201)
        assert record["status"] == "PENDING_REVIEW"
        assert record["hours_credited"] == 0

    def test_admin_approve_credits_hours(self, api, admin_headers):
        """PRD §3.10: "A `PlatformAdmin` then approves or rejects.
        Approval requires `status` to be `PENDING_REVIEW`, sets
        `hours_credited` to `hours_claimed`..."
        """
        counselor = create_counselor()
        res = api.create_ce_record(
            create_ce_record_payload(
                counselor_id=counselor["id"],
                hours_claimed=8.0,
            ),
            make_counselor_headers(counselor["id"]),
        )
        record = validate_success(res, expected_status=201)
        approve_res = api.approve_ce_record(record["id"], admin_headers)
        approved = validate_success(approve_res, expected_status=200)
        assert approved["status"] == "APPROVED"
        assert approved["hours_credited"] == 8.0


class TestCertificationCycleAutoCreated:
    def test_cycle_1_auto_created_with_required_fields(self, api):
        """PRD §3.1: "The platform automatically opens that counselor's
        first `CertificationCycle` in the `OPEN` state with `cycle_index`
        of 1, `required_supervision_hours` of 40 (frozen at cycle creation
        — the first cycle's bar is forty supervision hours, every
        subsequent cycle's bar is twenty), `required_ce_hours` of 12,
        `window_start_at` equal to the counselor's `created_at`, and
        `window_end_at` equal to that instant plus 365 days."
        """
        counselor = create_counselor()
        cycle = fetch_open_cycle_for(counselor["id"])
        assert cycle["cycle_index"] == 1
        assert float(cycle["required_supervision_hours"]) == 40.0
        assert float(cycle["required_ce_hours"]) == 12.0
        # window_start_at == counselor.created_at (PRD §3.1)
        assert cycle["window_start_at"] == counselor["created_at"]
