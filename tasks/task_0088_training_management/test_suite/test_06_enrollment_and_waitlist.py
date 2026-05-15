"""Enrollment: creation, eligibility, capacity, waitlist, and cancellation
cascades (PRD §3.4)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    assert_enrollment,
    cancel_enrollment,
    cancel_session_payload,
    create_enrollment_payload,
    create_session,
    create_trainee,
    enroll_trainee,
    find_row,
    iso_utc,
    make_trainee_headers,
    run_sweep,
    setup_open_session,
    setup_two_confirmed_with_waitlist,
    validate_error,
    validate_success,
)


SESSION_START = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
SESSION_END = datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)
ENROLL_DEADLINE = datetime(2026, 5, 31, 23, 0, tzinfo=timezone.utc)


# ===========================================================================
# Auto-confirm path (PRD §3.4)
# ===========================================================================
class TestUnchargedAutoConfirm:

    def test_uncharged_course_open_capacity_auto_confirms(
        self, api,
    ):
        """PRD §3.4: "For an uncharged course, when the session has
        open capacity (enrolled_count is strictly below capacity), the
        enrollment is auto-confirmed: it begins life in CONFIRMED
        directly and the session's enrolled_count is incremented by one."

        Claim: SELF enrollment in an uncharged open session ->
        status=CONFIRMED.
        """
        env = setup_open_session(capacity=10, is_charged=False)
        trainee = create_trainee(job_level=5)
        enrollment = enroll_trainee(env["session"]["id"], trainee, mode="SELF")
        assert_enrollment(enrollment)
        assert enrollment["status"] == "CONFIRMED"

    def test_enrolled_count_increments_on_confirm(self, api,
                                                  training_admin_headers):
        """PRD §3.4: "the session's enrolled_count is incremented by one."

        Claim: after one auto-confirm, session.enrolled_count == 1.
        """
        env = setup_open_session(capacity=10, is_charged=False)
        trainee = create_trainee(job_level=5)
        enroll_trainee(env["session"]["id"], trainee, mode="SELF")
        resp = api.get_session(env["session"]["id"], training_admin_headers)
        data = validate_success(resp, expected_status=200)
        assert data["enrolled_count"] == 1


# ===========================================================================
# Charged course approval flow (PRD §3.4)
# ===========================================================================
class TestChargedApprovalFlow:

    def test_charged_course_enrollment_starts_pending_approval(self, api):
        """PRD §3.4: "For a charged course, the enrollment begins life
        in PENDING_APPROVAL regardless of capacity and awaits an
        explicit approve or reject by a DepartmentManager."

        Claim: enrollment in a charged course -> PENDING_APPROVAL.
        """
        env = setup_open_session(capacity=10, is_charged=True)
        trainee = create_trainee(job_level=5)
        enrollment = enroll_trainee(env["session"]["id"], trainee, mode="SELF")
        assert enrollment["status"] == "PENDING_APPROVAL"

    def test_approve_pending_advances_to_confirmed(self, api,
                                                    department_manager_headers):
        """PRD §3.4: "Approval by a DepartmentManager advances a
        PENDING_APPROVAL enrollment to CONFIRMED. The transition
        requires that the session is ENROLLMENT_OPEN, that the
        session still has open capacity ... and that the trainee
        passes the eligibility checks above."

        Claim: approve on PENDING_APPROVAL -> CONFIRMED.
        """
        env = setup_open_session(capacity=10, is_charged=True)
        trainee = create_trainee(job_level=5)
        enrollment = enroll_trainee(env["session"]["id"], trainee, mode="SELF")
        assert enrollment["status"] == "PENDING_APPROVAL"
        resp = api.approve_enrollment(enrollment["id"],
                                      department_manager_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CONFIRMED"

    def test_reject_pending_advances_to_cancelled(
        self, api, department_manager_headers,
    ):
        """PRD §3.4: "Rejection by a DepartmentManager advances a
        PENDING_APPROVAL enrollment to CANCELLED, also writing an
        audit row."

        Claim: reject on PENDING_APPROVAL -> CANCELLED.
        """
        from test_helpers import reject_enrollment_payload
        env = setup_open_session(capacity=10, is_charged=True)
        trainee = create_trainee(job_level=5)
        enrollment = enroll_trainee(env["session"]["id"], trainee, mode="SELF")
        resp = api.reject_enrollment(
            enrollment["id"], reject_enrollment_payload(reason="manager"),
            department_manager_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CANCELLED"


# ===========================================================================
# Duplicate enrollment (PRD §3.4)
# ===========================================================================
class TestDuplicateEnrollment:

    def test_duplicate_enrollment_rejected(self, api):
        """PRD §3.4: "The same trainee cannot hold two non-CANCELLED
        enrollments for the same session — a second attempt returns
        ERR_DUPLICATE_ENROLLMENT."

        Claim: enrolling the same trainee twice -> ERR_DUPLICATE_ENROLLMENT.
        """
        env = setup_open_session(capacity=10, is_charged=False)
        trainee = create_trainee(job_level=5)
        enroll_trainee(env["session"]["id"], trainee, mode="SELF")
        # Second attempt by the same trainee.
        payload = create_enrollment_payload(
            session_id=env["session"]["id"],
            trainee_id=trainee["id"],
            mode="SELF",
        )
        resp = api.create_enrollment(payload, make_trainee_headers(trainee["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT.value)


# ===========================================================================
# Capacity and waitlist (PRD §3.4)
# ===========================================================================
class TestCapacityAndWaitlist:

    def test_when_capacity_full_loser_goes_to_waitlist(self, api):
        """PRD §3.4: "when the session is at capacity but has room on
        the waitlist (waitlist_count is strictly below
        waitlist_capacity), the enrollment is placed in WAITLISTED
        with a one-indexed waitlist_position equal to the new
        waitlist_count after increment."

        Claim: second enrollment in a capacity=1 session lands in
        WAITLISTED with waitlist_position=1.
        """
        env = setup_open_session(capacity=1, waitlist_capacity=5,
                                 is_charged=False)
        t1 = create_trainee(job_level=5)
        t2 = create_trainee(job_level=5)
        first = enroll_trainee(env["session"]["id"], t1)
        assert first["status"] == "CONFIRMED"
        second = enroll_trainee(env["session"]["id"], t2)
        assert second["status"] == "WAITLISTED"
        assert second["waitlist_position"] == 1

    def test_full_capacity_and_waitlist_rejects_session_at_capacity(self, api):
        """PRD §3.4: "If the session is already at capacity (its
        enrolled_count equals capacity) and its waitlist_count equals
        waitlist_capacity, the request is rejected with
        ERR_SESSION_AT_CAPACITY."

        Claim: capacity=1, waitlist_capacity=1, both full -> next
        enrollment returns ERR_SESSION_AT_CAPACITY.
        """
        env = setup_open_session(capacity=1, waitlist_capacity=1,
                                 is_charged=False)
        trainees = [create_trainee(job_level=5) for _ in range(3)]
        first = enroll_trainee(env["session"]["id"], trainees[0])
        assert first["status"] == "CONFIRMED"
        second = enroll_trainee(env["session"]["id"], trainees[1])
        assert second["status"] == "WAITLISTED"
        # Third attempt — neither seat nor waitlist room.
        payload = create_enrollment_payload(
            session_id=env["session"]["id"],
            trainee_id=trainees[2]["id"],
            mode="SELF",
        )
        resp = api.create_enrollment(
            payload, make_trainee_headers(trainees[2]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_AT_CAPACITY.value)


# ===========================================================================
# Waitlist FIFO promotion on cancel (PRD §3.4)
# ===========================================================================
class TestWaitlistFifoPromotion:

    def test_cancel_confirmed_promotes_waitlist_head(self, api,
                                                     training_admin_headers):
        """PRD §3.4: "When a CONFIRMED enrollment is cancelled and the
        waitlist is non-empty and the session is still ENROLLMENT_OPEN
        with the clock strictly before enrollment_deadline, the head
        of the waitlist — the row with the lowest waitlist_position —
        is promoted to CONFIRMED as a cascade hop: its status
        changes, the session's waitlist_count is decremented and its
        enrolled_count is incremented, and every remaining WAITLISTED
        row has its waitlist_position decreased by one to preserve the
        contiguous numbering."

        Claim: cancel of T1 promotes T2 to CONFIRMED and T3
        waitlist_position drops to 1.
        """
        ctx = setup_two_confirmed_with_waitlist(capacity=1,
                                                waitlist_capacity=3)
        env = ctx["env"]
        trainees = ctx["trainees"]
        enrollments = ctx["enrollments"]
        # Before: T1=CONFIRMED, T2=WAITLISTED(1), T3=WAITLISTED(2).
        assert enrollments[0]["status"] == "CONFIRMED"
        assert enrollments[1]["status"] == "WAITLISTED"
        assert enrollments[1]["waitlist_position"] == 1
        assert enrollments[2]["status"] == "WAITLISTED"
        assert enrollments[2]["waitlist_position"] == 2

        # Cancel T1 as that trainee (PRD §2.1: ownership compares
        # X-User-ID against enrollment.trainee_id).
        cancel_enrollment(enrollments[0]["id"], trainees[0])

        # Refresh each enrollment via the list endpoint.
        from test_helpers import validate_paginated
        resp = api.list_enrollments(training_admin_headers,
                                    params={"session_id": env["session"]["id"]})
        # The endpoint is a list — use validate_paginated which expects
        # the envelope to be paginated. PRD §2.3 says all list
        # endpoints honour limit/offset.
        rows, _ = validate_paginated(resp)
        e1 = find_row(rows, id=enrollments[0]["id"])
        e2 = find_row(rows, id=enrollments[1]["id"])
        e3 = find_row(rows, id=enrollments[2]["id"])
        assert e1 is not None and e2 is not None and e3 is not None
        assert e1["status"] == "CANCELLED"
        assert e2["status"] == "CONFIRMED"
        assert e3["status"] == "WAITLISTED"
        assert e3["waitlist_position"] == 1

        # Session counters.
        s_resp = api.get_session(env["session"]["id"], training_admin_headers)
        s = validate_success(s_resp, expected_status=200)
        assert s["enrolled_count"] == 1
        assert s["waitlist_count"] == 1


# ===========================================================================
# Eligibility (PRD §3.4)
# ===========================================================================
class TestEligibility:

    # DELETED: test_inactive_trainee_cannot_enroll
    # PRD §3.8 silence: PRD says HR employee.updated "may mutate the
    # matching Trainee row" — the word "may" leaves it
    # implementation-defined whether HR sync changes Trainee.status.
    # Without that mutation, no PRD-faithful path exists to drive a
    # Trainee into ON_LEAVE/OFFBOARDED in tests. Failed STEP 1b
    # unique-derivability (DEFAULT-VALUE SILENCE on HR-sync semantics).
    pass


# ===========================================================================
# Enrollment deadline (PRD §3.4)
# ===========================================================================
class TestEnrollmentDeadline:

    def test_enrollment_after_deadline_rejected(self, api):
        """PRD §3.4: "At the moment of creation, the session must
        already be ENROLLMENT_OPEN and the current clock must be
        strictly before enrollment_deadline, or the request is
        rejected with ERR_ENROLLMENT_DEADLINE_PASSED."

        Claim: with clock >= enrollment_deadline (and session moved
        to ENROLLMENT_CLOSED) -> ERR_ENROLLMENT_DEADLINE_PASSED.
        """
        env = setup_open_session(
            capacity=10, is_charged=False,
            start_at=SESSION_START, end_at=SESSION_END,
            enrollment_deadline=ENROLL_DEADLINE,
        )
        trainee = create_trainee(job_level=5)
        # Advance past the deadline.
        advance_clock_to(ENROLL_DEADLINE + timedelta(minutes=1))
        run_sweep()
        payload = create_enrollment_payload(
            session_id=env["session"]["id"],
            trainee_id=trainee["id"],
            mode="SELF",
        )
        resp = api.create_enrollment(payload,
                                     make_trainee_headers(trainee["id"]))
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_DEADLINE_PASSED.value)


# ===========================================================================
# Session cancel cascades to enrollments (PRD §3.3)
# ===========================================================================
class TestSessionCancelCascade:

    def test_session_cancel_cancels_confirmed_and_waitlisted(
        self, api, training_admin_headers,
    ):
        """PRD §3.3: "Cancellation triggers a uniform cascade: every
        Enrollment belonging to this session whose status is currently
        PENDING_APPROVAL, CONFIRMED, or WAITLISTED is transitioned to
        CANCELLED."

        Claim: cancel of a session whose enrollments include CONFIRMED
        + WAITLISTED rows cancels both.
        """
        ctx = setup_two_confirmed_with_waitlist(capacity=1,
                                                waitlist_capacity=3)
        env = ctx["env"]
        enrollments = ctx["enrollments"]
        # Cancel the session — clock is well before start, so no fee.
        advance_clock_to(SESSION_START - timedelta(days=10))
        resp = api.cancel_session(
            env["session"]["id"],
            cancel_session_payload(reason="Cascade test"),
            training_admin_headers,
        )
        validate_success(resp, expected_status=200)
        # Refresh enrollments.
        from test_helpers import validate_paginated
        list_resp = api.list_enrollments(
            training_admin_headers,
            params={"session_id": env["session"]["id"]},
        )
        rows, _ = validate_paginated(list_resp)
        for e in enrollments:
            row = find_row(rows, id=e["id"])
            assert row is not None
            assert row["status"] == "CANCELLED", (
                f"Enrollment {e['id']} should be CANCELLED after session "
                f"cancel; got {row['status']}"
            )
