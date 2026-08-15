"""Callback appointment conflicts: one-sided buffer overlap semantics, session
capacity boundary, and the booked_count gauge invariant (PRD sections 2.9, 3.5)."""
from test_helpers import (
    ApiErrorId,
    advance_to_shortlisted,
    assert_session,
    create_breakdown,
    create_production,
    create_role,
    create_session,
    create_talent,
    propose_appointment,
    release_breakdown,
    set_clock,
    setup_released_breakdown,
    setup_shortlisted_submission,
    submit_talent,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ASSOCIATE = TEST_USERS["associate_headers"]


def _appointment_for_talent(api, production_id, talent, character_name, slot_start, slot_end, buffer_minutes=None):
    """Fresh role/breakdown/submission for the same talent (a second active
    submission on the same breakdown would be auto-rejected as a duplicate), a
    session on that breakdown, and one PROPOSED appointment in it."""
    role = create_role(production_id, character_name=character_name)
    breakdown = create_breakdown(production_id, role["id"])
    breakdown = release_breakdown(breakdown["id"])
    submission = submit_talent(breakdown["id"], talent["id"])
    advance_to_shortlisted(submission["id"])
    session = create_session(breakdown["id"], capacity=10)
    overrides = {"slot_start": slot_start, "slot_end": slot_end}
    if buffer_minutes is not None:
        overrides["buffer_minutes"] = buffer_minutes
    appointment = propose_appointment(session["id"], submission["id"], **overrides)
    return {"role": role, "breakdown": breakdown, "submission": submission, "session": session, "appointment": appointment}


class TestTalentOverlapSemantics:
    def test_overlapping_confirm_with_onesided_buffer_rejected(self, api):
        """PRD section 3.5: "First, the talent-conflict check: a conflict exists
        exactly when some other `CONFIRMED` appointment belonging to the same
        talent (via its submission) has a `slot_start` strictly earlier than the
        new appointment's effective end — the new appointment's `slot_end`
        extended by its own `buffer_minutes` — while the new appointment's
        `slot_start` is strictly earlier than that existing appointment's
        `slot_end`."
        PRD section 3.5: "A collision is rejected with `ERR_TALENT_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/appointment_overlap_onesided_buffer_semantics
        """
        set_clock("2026-08-03T00:00:00Z")
        production = create_production()
        talent = create_talent()
        first = _appointment_for_talent(
            api, production["id"], talent, "OR-a", "2026-08-04T09:00:00Z", "2026-08-04T09:30:00Z"
        )
        validate_success(api.confirm_appointment(first["appointment"]["id"], ASSOCIATE))
        second = _appointment_for_talent(
            api, production["id"], talent, "OR-b", "2026-08-04T09:20:00Z", "2026-08-04T09:50:00Z", buffer_minutes=15
        )
        resp = api.confirm_appointment(second["appointment"]["id"], ASSOCIATE)
        validate_error(resp, ApiErrorId.ERR_TALENT_CONFLICT)

    def test_adjacent_appointment_is_not_a_conflict(self, api):
        """PRD section 3.5: "Adjacency is not a conflict: an existing appointment
        whose `slot_end` equals the new `slot_start` passes cleanly."
        PRD section 3.5: "The buffer is one-sided by design — only the new
        appointment's buffer extends its tail; the existing appointment's own
        buffer is ignored entirely."

        Design: Difficulty/resource_temporal_overlap/appointment_overlap_onesided_buffer_semantics
        """
        set_clock("2026-08-03T00:00:00Z")
        production = create_production()
        talent = create_talent()
        first = _appointment_for_talent(
            api, production["id"], talent, "ADJ-a", "2026-08-04T09:00:00Z", "2026-08-04T09:30:00Z"
        )
        validate_success(api.confirm_appointment(first["appointment"]["id"], ASSOCIATE))
        adjacent = _appointment_for_talent(
            api, production["id"], talent, "ADJ-b", "2026-08-04T09:30:00Z", "2026-08-04T10:00:00Z"
        )
        resp = api.confirm_appointment(adjacent["appointment"]["id"], ASSOCIATE)
        data = validate_success(resp)
        assert data["status"] == "CONFIRMED", "existing slot_end == new slot_start passes cleanly (half-open boundary)"


class TestSessionCapacityBoundary:
    def _setup_session_with_confirmed(self, api, capacity, confirmed_count):
        """One breakdown, one session with `capacity`, and `confirmed_count`
        CONFIRMED appointments of distinct talents; returns (ctx, session, extra
        PROPOSED appointment of a fresh talent)."""
        ctx = setup_released_breakdown()
        session = create_session(ctx["breakdown"]["id"], capacity=capacity)
        confirmed = []
        for i in range(confirmed_count):
            talent = create_talent()
            submission = submit_talent(ctx["breakdown"]["id"], talent["id"])
            advance_to_shortlisted(submission["id"])
            # Slots for distinct talents never talent-conflict; keep them disjoint anyway.
            start_minutes = 9 * 60 + i * 30
            end_minutes = start_minutes + 30
            appointment = propose_appointment(
                session["id"],
                submission["id"],
                slot_start=f"2026-08-04T{start_minutes // 60:02d}:{start_minutes % 60:02d}:00Z",
                slot_end=f"2026-08-04T{end_minutes // 60:02d}:{end_minutes % 60:02d}:00Z",
            )
            resp = api.confirm_appointment(appointment["id"], ASSOCIATE)
            confirmed.append(validate_success(resp))
        extra_talent = create_talent()
        extra_submission = submit_talent(ctx["breakdown"]["id"], extra_talent["id"])
        advance_to_shortlisted(extra_submission["id"])
        extra_appointment = propose_appointment(
            session["id"], extra_submission["id"], slot_start="2026-08-04T11:00:00Z", slot_end="2026-08-04T11:30:00Z"
        )
        return ctx, session, confirmed, extra_appointment

    def test_confirm_at_capacity_rejected(self, api):
        """PRD section 3.5: "Second, the capacity check: the session's
        `booked_count` must still be below `capacity` at confirm time, and a
        confirm arriving when the count has already reached capacity is rejected
        with `ERR_SESSION_FULL` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/session_capacity_at_capacity_rejects
        """
        set_clock("2026-08-03T00:00:00Z")
        _, session, _, extra = self._setup_session_with_confirmed(api, capacity=2, confirmed_count=2)
        pre = validate_success(api.get_session(session["id"], ASSOCIATE))
        assert pre["booked_count"] == 2, "session sits exactly at capacity before the trigger"
        resp = api.confirm_appointment(extra["id"], ASSOCIATE)
        validate_error(resp, ApiErrorId.ERR_SESSION_FULL)

    def test_confirm_below_capacity_succeeds(self, api):
        """PRD section 3.5: "the session's `booked_count` must still be below
        `capacity` at confirm time".
        PRD section 3.5: "A successful confirm moves `PROPOSED → CONFIRMED`,
        recomputes the session's `booked_count` upward by one".

        Design: Difficulty/boundary_precision_check/session_capacity_at_capacity_rejects
        """
        set_clock("2026-08-03T00:00:00Z")
        _, session, _, extra = self._setup_session_with_confirmed(api, capacity=2, confirmed_count=1)
        pre = validate_success(api.get_session(session["id"], ASSOCIATE))
        assert pre["booked_count"] == 1, "one below capacity before the trigger"
        resp = api.confirm_appointment(extra["id"], ASSOCIATE)
        data = validate_success(resp)
        assert data["status"] == "CONFIRMED"
        after = validate_success(api.get_session(session["id"], ASSOCIATE))
        assert after["booked_count"] == 2


class TestBookedCountInvariant:
    def test_confirm_then_cancel_restores_booked_count(self, api):
        """PRD section 2.9: "A session's `booked_count` is the count of its child
        callback appointments in `CONFIRMED` status, recomputed whenever an
        appointment is confirmed, cancelled, completed, or swept to no-show."
        PRD section 3.5: "Cancelling — from `PROPOSED` or `CONFIRMED` to
        `CANCELLED`, an associate's action — recomputes `booked_count` downward by
        one when the cancelled appointment had been `CONFIRMED`".

        Design: Difficulty/compensating_invariant/session_booked_count_confirm_cancel_invariant
        """
        ctx = setup_shortlisted_submission()
        session = create_session(ctx["breakdown"]["id"])
        appointment = propose_appointment(session["id"], ctx["submission"]["id"])
        before = validate_success(api.get_session(session["id"], ASSOCIATE))
        assert before["booked_count"] == 0
        validate_success(api.confirm_appointment(appointment["id"], ASSOCIATE))
        after_confirm = validate_success(api.get_session(session["id"], ASSOCIATE))
        assert after_confirm["booked_count"] == 1, "confirm recomputes the gauge upward by one"
        validate_success(api.cancel_appointment(appointment["id"], ASSOCIATE))
        after_cancel = validate_success(api.get_session(session["id"], ASSOCIATE))
        assert_session(after_cancel)
        assert after_cancel["booked_count"] == 0, (
            "cancelling the CONFIRMED appointment returns booked_count to its prior value"
        )

    def test_partial_cancel_leaves_remaining_confirmation_counted(self, api):
        """PRD section 2.9: "A session's `booked_count` is the count of its child
        callback appointments in `CONFIRMED` status, recomputed whenever an
        appointment is confirmed, cancelled, completed, or swept to no-show."

        Design: Difficulty/compensating_invariant/session_booked_count_confirm_cancel_invariant
        """
        set_clock("2026-08-03T00:00:00Z")
        ctx = setup_released_breakdown()
        session = create_session(ctx["breakdown"]["id"])
        appointments = []
        for i in range(2):
            talent = create_talent()
            submission = submit_talent(ctx["breakdown"]["id"], talent["id"])
            advance_to_shortlisted(submission["id"])
            appointment = propose_appointment(
                session["id"],
                submission["id"],
                slot_start=f"2026-08-04T{9 + i:02d}:00:00Z",
                slot_end=f"2026-08-04T{9 + i:02d}:30:00Z",
            )
            appointments.append(validate_success(api.confirm_appointment(appointment["id"], ASSOCIATE)))
        mid = validate_success(api.get_session(session["id"], ASSOCIATE))
        assert mid["booked_count"] == 2
        validate_success(api.cancel_appointment(appointments[0]["id"], ASSOCIATE))
        after = validate_success(api.get_session(session["id"], ASSOCIATE))
        assert after["booked_count"] == 1, "only the surviving CONFIRMED appointment is counted"
        survivor = validate_success(api.get_appointment(appointments[1]["id"], ASSOCIATE))
        assert survivor["status"] == "CONFIRMED"
