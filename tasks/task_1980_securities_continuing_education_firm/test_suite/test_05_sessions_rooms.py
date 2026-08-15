"""Sessions, rooms, blackout windows: seat accounting boundary, half-open
room overlap, closed-interval blackout conflicts."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_approved_content,
    create_blackout,
    create_enrollment,
    create_instructor_led_setup,
    create_rep,
    create_session_payload,
    get_success_data,
    validate_error,
    validate_success,
)


class TestSeatBoundary:
    """capacity 2: enrollments 1 and 2 succeed; the third is rejected."""

    def _setup_capacity_two(self, api):
        r1 = create_rep(crd_number="CRD-SB1")
        r2 = create_rep(crd_number="CRD-SB2")
        r3 = create_rep(crd_number="CRD-SB3")
        content, session = create_instructor_led_setup(
            capacity=2, room_name="Room-Seat",
            start_at="2026-09-16T09:00:00Z", end_at="2026-09-16T11:00:00Z")
        return (r1, r2, r3), content, session

    def test_first_and_second_enrollments_succeed(self, api, admin_headers):
        """PRD §3.4: "the session to be `SCHEDULED` (`ERR_SESSION_NOT_SCHEDULED`)
        with at least one seat still free, meaning the session's active seat
        holders are fewer than its `capacity` (`ERR_SESSION_FULL`)."

        Design: Difficulty/boundary_precision_check/session_seat_boundary_exact_capacity
        """
        (r1, r2, _r3), _content, session = self._setup_capacity_two(api)
        e1 = create_enrollment(r1["id"], session_id=session["id"])
        e2 = create_enrollment(r2["id"], session_id=session["id"])
        assert e1["enrollment_status"] == "ENROLLED"
        assert e2["enrollment_status"] == "ENROLLED"

    def test_third_enrollment_rejected_session_full(self, api, admin_headers):
        """PRD §3.4: "the session to be `SCHEDULED` (`ERR_SESSION_NOT_SCHEDULED`)
        with at least one seat still free, meaning the session's active seat
        holders are fewer than its `capacity` (`ERR_SESSION_FULL`)."

        Design: Difficulty/boundary_precision_check/session_seat_boundary_exact_capacity
        """
        (r1, r2, r3), _content, session = self._setup_capacity_two(api)
        create_enrollment(r1["id"], session_id=session["id"])
        create_enrollment(r2["id"], session_id=session["id"])

        mid = validate_success(api.get_session(session["id"], admin_headers))
        assert mid["available_seats"] == 0, (
            f"at the capacity boundary available_seats must read exactly 0, "
            f"got {mid['available_seats']}")

        resp = api.create_enrollment(
            {"rep_id": r3["id"], "session_id": session["id"]}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_SESSION_FULL)


class TestSeatLedgerInvariant:
    """Enroll + cancel pair returns available_seats to its pre-enroll value."""

    def test_enroll_consumes_seat(self, api, admin_headers):
        """PRD §3.3: "Seat accounting is a conserved invariant:
        `available_seats` always equals `capacity` minus the number of
        enrollments linked to the session that are in `ENROLLED`,
        `IN_PROGRESS`, or `COMPLETED`; enrollments in `FAILED`, `CANCELLED`,
        `EXPIRED`, or `VOIDED` hold no seat."

        Design: Difficulty/compensating_invariant/seat_ledger_enroll_cancel_invariant
        """
        rep = create_rep(crd_number="CRD-INV1")
        _content, session = create_instructor_led_setup(
            capacity=2, room_name="Room-Inv",
            start_at="2026-09-20T09:00:00Z", end_at="2026-09-20T10:00:00Z")
        assert session["available_seats"] == 2

        create_enrollment(rep["id"], session_id=session["id"])
        mid = validate_success(api.get_session(session["id"], admin_headers))
        assert mid["available_seats"] == 1, (
            f"enrollment must consume one seat, got {mid['available_seats']}")

    def test_enroll_then_cancel_restores_seat(self, api, admin_headers):
        """PRD §3.3: "The invariant must hold after every mutation — in
        particular, an enroll-then-cancel pair on the same session returns
        `available_seats` to exactly its pre-enrollment value."

        Design: Difficulty/compensating_invariant/seat_ledger_enroll_cancel_invariant
        """
        rep = create_rep(crd_number="CRD-INV1b")
        _content, session = create_instructor_led_setup(
            capacity=2, room_name="Room-Inv2",
            start_at="2026-09-20T09:00:00Z", end_at="2026-09-20T10:00:00Z")
        enr = create_enrollment(rep["id"], session_id=session["id"])
        get_success_data(api.cancel_enrollment(enr["id"], admin_headers))
        after = validate_success(api.get_session(session["id"], admin_headers))
        assert after["available_seats"] == 2, (
            f"enroll+cancel must leave the seat ledger unchanged at 2, "
            f"got {after['available_seats']}")


class TestRoomOverlapHalfOpen:
    """Half-open [start, end) room semantics: adjacency allowed, overlap not."""

    def test_adjacent_session_allowed(self, api, admin_headers):
        """PRD §3.3: "First, rooms cannot be double-booked: a new session
        conflicts with an existing one when both share the same `room_name`,
        the existing session has not been `CANCELLED`, and each session starts
        strictly before the other ends — because the end instant is exclusive,
        back-to-back sessions, where one starts exactly when the other ends, do
        not conflict."

        Design: Difficulty/resource_temporal_overlap/room_overlap_half_open_adjacency_allowed
        """
        content = create_approved_content(
            code="ILT-RM", delivery_format="INSTRUCTOR_LED", credit_hours=2.0)
        s1 = get_success_data(api.create_session(
            create_session_payload(
                content["id"], room_name="Room-Ovl",
                start_at="2026-09-01T09:00:00Z", end_at="2026-09-01T11:00:00Z"),
            admin_headers))
        # Back-to-back: starts exactly when s1 ends — must NOT conflict.
        s2 = get_success_data(api.create_session(
            create_session_payload(
                content["id"], room_name="Room-Ovl",
                start_at="2026-09-01T11:00:00Z", end_at="2026-09-01T12:00:00Z"),
            admin_headers))
        assert s2["session_status"] == "SCHEDULED", (
            "adjacent session (start == prior end) must be created under "
            "half-open semantics")

    def test_overlapping_session_rejected(self, api, admin_headers):
        """PRD §3.3: "a new session conflicts with an existing one when both
        share the same `room_name`, the existing session has not been
        `CANCELLED`, and each session starts strictly before the other ends ...
        A violating request is rejected with `ERR_ROOM_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/room_overlap_half_open_adjacency_allowed
        """
        content = create_approved_content(
            code="ILT-RM2", delivery_format="INSTRUCTOR_LED", credit_hours=2.0)
        get_success_data(api.create_session(
            create_session_payload(
                content["id"], room_name="Room-Ovl2",
                start_at="2026-09-01T09:00:00Z", end_at="2026-09-01T11:00:00Z"),
            admin_headers))
        # Genuine intersection: [10:30, 11:30) overlaps [09:00, 11:00).
        resp = api.create_session(
            create_session_payload(
                content["id"], room_name="Room-Ovl2",
                start_at="2026-09-01T10:30:00Z", end_at="2026-09-01T11:30:00Z"),
            admin_headers)
        validate_error(resp, ApiErrorId.ERR_ROOM_CONFLICT)


class TestBlackoutClosedInterval:
    """Blackout windows use closed-interval semantics: touching conflicts."""

    def test_touching_session_conflicts(self, api, admin_headers):
        """PRD §3.3: "A session conflicts with a blackout window when the
        session's `start_at` is at or before the blackout's `end_at` and the
        blackout's `start_at` is at or before the session's `end_at`; because
        the blackout interval is closed, merely touching a blackout boundary
        already conflicts, and the scheduling request is rejected with
        `ERR_BLACKOUT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/blackout_overlap_closed_interval_touching_conflicts
        """
        content = create_approved_content(
            code="ILT-BL", delivery_format="INSTRUCTOR_LED", credit_hours=2.0)
        create_blackout(
            label="regulatory exam window",
            start_at="2026-09-10T00:00:00Z", end_at="2026-09-11T00:00:00Z")
        # Session end_at == blackout start_at: touching conflicts (closed).
        resp = api.create_session(
            create_session_payload(
                content["id"], room_name="Room-Bl",
                start_at="2026-09-09T23:00:00Z", end_at="2026-09-10T00:00:00Z"),
            admin_headers)
        validate_error(resp, ApiErrorId.ERR_BLACKOUT_CONFLICT)

    def test_disjoint_session_allowed(self, api, admin_headers):
        """PRD §3.3: "A session conflicts with a blackout window when the
        session's `start_at` is at or before the blackout's `end_at` and the
        blackout's `start_at` is at or before the session's `end_at`."

        Design: Difficulty/resource_temporal_overlap/blackout_overlap_closed_interval_touching_conflicts
        """
        content = create_approved_content(
            code="ILT-BL2", delivery_format="INSTRUCTOR_LED", credit_hours=2.0)
        create_blackout(
            label="regulatory exam window",
            start_at="2026-09-10T00:00:00Z", end_at="2026-09-11T00:00:00Z")
        # Fully after the blackout: no conflict.
        session = get_success_data(api.create_session(
            create_session_payload(
                content["id"], room_name="Room-Bl2",
                start_at="2026-09-12T09:00:00Z", end_at="2026-09-12T10:00:00Z"),
            admin_headers))
        assert session["session_status"] == "SCHEDULED"


class TestSessionGuards:
    def test_enroll_into_cancelled_session_rejected(self, api, admin_headers):
        """PRD §3.4: "Creation further requires ... when session-linked — the
        session to be `SCHEDULED` (`ERR_SESSION_NOT_SCHEDULED`)."
        PRD §3.3: "A `TrainingAdmin` may cancel a session while it is
        `SCHEDULED`; cancelling a session in any other status is rejected with
        `ERR_SESSION_NOT_SCHEDULED`."

        Design: Corner/errors/c_enroll_into_cancelled_session_returns_409
        """
        rep = create_rep(crd_number="CRD-ESC")
        content, session = create_instructor_led_setup(
            capacity=5, room_name="Room-Esc",
            start_at="2026-10-12T09:00:00Z", end_at="2026-10-12T11:00:00Z")
        get_success_data(api.cancel_session(session["id"], admin_headers))

        resp = api.create_enrollment(
            {"rep_id": rep["id"], "session_id": session["id"]}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_SCHEDULED)


class TestBlackoutWindowShape:
    def test_zero_length_window_rejected(self, api, officer_headers):
        """PRD §2.6: "Window sanity is checked at the same stage: a session,
        blackout, license period, or renewal window whose end is not strictly
        later than its start yields `ERR_WINDOW_INVALID` (HTTP 400)."

        Design: Corner/validations/c_blackout_invalid_window_returns_400
        """
        resp = api.create_blackout_window(
            {"label": "zero-length",
             "start_at": "2026-09-10T00:00:00Z",
             "end_at": "2026-09-10T00:00:00Z"},
            officer_headers)
        validate_error(resp, ApiErrorId.ERR_WINDOW_INVALID)
