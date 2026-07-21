"""Temporal scheduling: fitter service buffer, member half-open overlap, the
temporal-beats-referential precedence, and fitment lifecycle guards.

Queue A (Difficulty): resource_temporal_overlap (fitter buffer, member
half-open), priority_pair_validation_conflict (temporal beats referential).
Queue B (Corner): state_machines (appointment-in-past, complete requires checked-in).
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    fixtures as fx,
)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / fitter_buffer_overlap_rejected
# ---------------------------------------------------------------------------
def test_fitter_buffer_overlap_rejected(api, sm):
    """PRD 3.8: "If the chosen fitter is already committed within a 15-minute
    service buffer of the requested window — that is, the gap between this window
    and any of the fitter's other sessions is less than 15 minutes on either side
    — it is rejected with `ERR_FITTER_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/fitter_buffer_overlap_rejected
    """
    ma = fx.create_member()
    mb = fx.create_member()
    fitter = fx.create_fitter("Fitter Fay")
    fx.create_fitment(ma["id"], fitter["id"], "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
    # Second window starts 10 minutes after the first ends -> inside the 15-min buffer.
    resp = api.create_fitment_session(
        {
            "member_id": mb["id"],
            "fitter_id": fitter["id"],
            "scheduled_start": "2026-08-01T11:10:00Z",
            "scheduled_end": "2026-08-01T12:00:00Z",
        },
        sm,
    )
    validate_error(resp, ApiErrorId.ERR_FITTER_UNAVAILABLE.value, 409)


def test_fitter_direct_overlap_rejected(api, sm):
    """PRD 3.8: "If the chosen fitter is already committed within a 15-minute
    service buffer of the requested window — that is, the gap between this window
    and any of the fitter's other sessions is less than 15 minutes on either side
    — it is rejected with `ERR_FITTER_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/fitter_buffer_overlap_rejected
    """
    ma = fx.create_member()
    mb = fx.create_member()
    fitter = fx.create_fitter("Fitter Fay")
    fx.create_fitment(ma["id"], fitter["id"], "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
    # Directly overlapping window on the same fitter (distinct member).
    resp = api.create_fitment_session(
        {
            "member_id": mb["id"],
            "fitter_id": fitter["id"],
            "scheduled_start": "2026-08-01T10:30:00Z",
            "scheduled_end": "2026-08-01T11:30:00Z",
        },
        sm,
    )
    validate_error(resp, ApiErrorId.ERR_FITTER_UNAVAILABLE.value, 409)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / member_halfopen_training_overlap_rejected
# ---------------------------------------------------------------------------
def test_member_halfopen_overlap_rejected(api, sm):
    """PRD 3.9: "the booking must not overlap the member's own existing schedule,
    or it fails with `ERR_SCHEDULE_CONFLICT` under the same half-open semantics
    as fitment."

    Design: Difficulty/resource_temporal_overlap/member_halfopen_training_overlap_rejected
    """
    member, _sub = fx.setup_member_with_active_subscription("PLUS")
    sx = fx.create_training_session("2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z", capacity=5, title="X")
    fx.book_training(sx["id"], member["id"])
    sy = fx.create_training_session("2026-08-02T10:30:00Z", "2026-08-02T11:30:00Z", capacity=5, title="Y")
    resp = api.create_training_booking(
        {"session_id": sy["id"], "member_id": member["id"]}, sm
    )
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT.value, 409)


def test_member_adjacent_booking_allowed(api, sm):
    """PRD 3.8: "member overlap uses half-open interval semantics, so two windows
    that merely touch end-to-start do not conflict."

    Design: Difficulty/resource_temporal_overlap/member_halfopen_training_overlap_rejected
    """
    member, _sub = fx.setup_member_with_active_subscription("PLUS")
    sx = fx.create_training_session("2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z", capacity=5, title="X")
    fx.book_training(sx["id"], member["id"])
    # Z starts exactly when X ends -> half-open windows merely touch, no conflict.
    sz = fx.create_training_session("2026-08-02T11:00:00Z", "2026-08-02T12:00:00Z", capacity=5, title="Z")
    resp = api.create_training_booking(
        {"session_id": sz["id"], "member_id": member["id"]}, sm
    )
    data = validate_success(resp, 201)
    assert data["status"] == "BOOKED"


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / booking_temporal_beats_referential
# ---------------------------------------------------------------------------
def test_booking_temporal_beats_referential(api, sm):
    """PRD 2.9: "the checks are evaluated in a fixed priority order and the first
    failure determines the returned error."
    PRD 3.9: "the booking must not overlap the member's own existing schedule, or
    it fails with `ERR_SCHEDULE_CONFLICT` under the same half-open semantics as
    fitment."

    Design: Difficulty/priority_pair_validation_conflict/booking_temporal_beats_referential
    """
    member = fx.create_member()
    sub = fx.create_subscription(member["id"], "BASIC")
    sx = fx.create_training_session("2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z", capacity=5, title="X run")
    fx.book_training(sx["id"], member["id"])
    get_success_data(api.cancel_subscription(sub["id"], sm))  # subscription no longer ACTIVE
    sy = fx.create_training_session("2026-08-05T10:30:00Z", "2026-08-05T11:30:00Z", capacity=5, title="Y run")
    # Overlap (temporal, priority 7) AND missing active subscription (referential,
    # priority 8) both fail; temporal wins.
    resp = api.create_training_booking(
        {"session_id": sy["id"], "member_id": member["id"]}, sm
    )
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT.value, 409)


def test_booking_temporal_beats_referential_second_window(api, sm):
    """PRD 2.9: "When a single request could fail more than one check, the checks
    are evaluated in a fixed priority order and the first failure determines the
    returned error."
    PRD 3.9: "the booking must not overlap the member's own existing schedule, or
    it fails with `ERR_SCHEDULE_CONFLICT` under the same half-open semantics as
    fitment."

    Design: Difficulty/priority_pair_validation_conflict/booking_temporal_beats_referential
    """
    member = fx.create_member()
    sub = fx.create_subscription(member["id"], "BASIC")
    sx = fx.create_training_session("2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z", capacity=5, title="X run")
    fx.book_training(sx["id"], member["id"])
    get_success_data(api.cancel_subscription(sub["id"], sm))
    sy2 = fx.create_training_session("2026-08-05T10:45:00Z", "2026-08-05T11:15:00Z", capacity=5, title="Y2 run")
    resp = api.create_training_booking(
        {"session_id": sy2["id"], "member_id": member["id"]}, sm
    )
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT.value, 409)


# ---------------------------------------------------------------------------
# Corner: state_machines
# ---------------------------------------------------------------------------
def test_fitment_in_past_rejected(api, sm):
    """PRD 3.8: "If `scheduled_start` is before the current clock, the booking is
    rejected with `ERR_APPOINTMENT_IN_PAST`."
    PRD 2.4: "At server startup the clock reads exactly `2026-07-01T00:00:00Z`,
    and before any operator sets it the clock returns that default rather than
    the machine's wall-clock time."

    Design: Corner/state_machines/c_fitment_in_past_rejected
    """
    member = fx.create_member()
    fitter = fx.create_fitter("Coach Lee")
    resp = api.create_fitment_session(
        {
            "member_id": member["id"],
            "fitter_id": fitter["id"],
            "scheduled_start": "2026-06-01T10:00:00Z",
            "scheduled_end": "2026-06-01T11:00:00Z",
        },
        sm,
    )
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_IN_PAST.value, 422)


def test_fitment_complete_requires_checked_in(api, sm):
    """PRD 3.8: "The fitter then completes the session, moving `CHECKED_IN` to
    `COMPLETED`"
    PRD 3.8: "Out-of-state transitions on a session yield `ERR_INVALID_STATE`."

    Design: Corner/state_machines/c_fitment_complete_requires_checked_in
    """
    member = fx.create_member()
    fitter = fx.create_fitter("Coach Kim")
    session = fx.create_fitment(
        member["id"], fitter["id"], "2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z"
    )  # SCHEDULED, not CHECKED_IN
    resp = api.complete_fitment(session["id"], {"notes": "premature"}, sm)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
