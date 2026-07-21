"""Appointment lifecycle transitions, post-surgical safety guards, and scheduling
interval semantics (fitter buffered overlap, room aggregate capacity).

Covers queue-A cross_entity_state_dependency, priority_pair_validation_conflict,
and resource_temporal_overlap, plus queue-B appointment state-machine instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_appointment_payload, create_fit_payload,
    ApiErrorId,
    make_customer_headers, make_fitter_headers,
    new_customer, new_fitter, new_room,
    setup_confirmed_appointment, setup_checked_in_appointment, setup_booked_appointment,
)


def _book(api, cust_id, fitter_id, room_id, fitting_type, start, duration=None):
    payload = create_appointment_payload(
        cust_id, fitter_id, room_id, fitting_type=fitting_type, scheduled_start=start
    )
    if duration is not None:
        payload["duration_minutes"] = duration
    return get_success_data(api.create_appointment(payload, make_customer_headers(cust_id)))


# ─── Lifecycle (queue B) ──────────────────────────────────────────────────
def test_confirm_already_confirmed_invalid_state(api):
    """PRD §3.2: "Confirmation, performed by the assigned Fitter, advances the
    appointment REQUESTED → CONFIRMED and locks the fitter, room, and time slot."
    PRD §3.7: "any state-transition request whose target is not in a legal
    originating state, and which is not covered by one of the more specific state
    errors named above, is rejected with the generic ERR_INVALID_STATE."

    Design: Corner/state_machines/confirm_already_confirmed_returns_invalid_state
    """
    ctx = setup_confirmed_appointment()
    res = api.confirm_appointment(ctx["appointment"]["id"], make_fitter_headers(ctx["fitter"]["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_complete_without_fit_rejected(api):
    """PRD §3.2: "Completion, by the Fitter, advances CHECKED_IN → COMPLETED, but only
    if a recommendation has been submitted — that is, recommended_size is not null;
    otherwise the request is rejected with ERR_FIT_NOT_SUBMITTED."

    Design: Corner/state_machines/complete_without_fit_returns_fit_not_submitted
    """
    ctx = setup_checked_in_appointment()
    res = api.complete_appointment(ctx["appointment"]["id"], make_fitter_headers(ctx["fitter"]["id"]))
    validate_error(res, ApiErrorId.ERR_FIT_NOT_SUBMITTED)


def test_reschedule_cycle_back_to_confirmed(api):
    """PRD §3.2: "The customer may instead reschedule from CONFIRMED back to
    REQUESTED, which releases the slot lock, optionally updates scheduled_start if a
    new value is provided, and requires re-confirmation; this is a deliberate cyclic
    revision loop."

    Design: Corner/state_machines/appointment_reschedule_cycle_reconfirm
    """
    ctx = setup_confirmed_appointment()
    appt_id, fitter_id = ctx["appointment"]["id"], ctx["fitter"]["id"]
    rescheduled = validate_success(
        api.reschedule_appointment(
            appt_id, {"scheduled_start": "2026-07-08T14:00:00Z"},
            make_customer_headers(ctx["customer"]["id"]),
        ),
        200,
    )
    assert rescheduled["status"] == "REQUESTED", rescheduled
    reconfirmed = validate_success(
        api.confirm_appointment(appt_id, make_fitter_headers(fitter_id)), 200
    )
    assert reconfirmed["status"] == "CONFIRMED", reconfirmed


def test_completed_appointment_terminal_lockdown(api):
    """PRD §3.2: "COMPLETED and CANCELLED are terminal."
    PRD §3.7: "any state-transition request whose target is not in a legal
    originating state, and which is not covered by one of the more specific state
    errors named above, is rejected with the generic ERR_INVALID_STATE."

    Design: Corner/state_machines/completed_appointment_terminal_lockdown
    """
    ctx = setup_checked_in_appointment()
    appt_id, fitter_id = ctx["appointment"]["id"], ctx["fitter"]["id"]
    validate_success(
        api.fit_appointment(
            appt_id, create_fit_payload(76, 84, ctx["version"], fit_preference="STANDARD"),
            make_fitter_headers(fitter_id),
        ),
        200,
    )
    completed = validate_success(api.complete_appointment(appt_id, make_fitter_headers(fitter_id)), 200)
    assert completed["status"] == "COMPLETED"
    res = api.confirm_appointment(appt_id, make_fitter_headers(fitter_id))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


# ─── Post-surgical safety guards (queue A + B) ────────────────────────────
def test_confirm_postsurgical_uncertified_fitter_rejected(api):
    """PRD §3.2: "When fitting_type is POST_SURGICAL or MASTECTOMY, the fitter must
    have post_surgical_certified true, or the request is rejected with
    ERR_FITTER_NOT_CERTIFIED".

    Design: Difficulty/cross_entity_state_dependency/confirm_postsurgical_requires_certified_fitter
    """
    ctx = setup_booked_appointment(
        fitting_type="POST_SURGICAL", post_surgical_certified=False, is_private=True,
        scheduled_start="2026-07-03T09:00:00Z",
    )
    res = api.confirm_appointment(ctx["appointment"]["id"], make_fitter_headers(ctx["fitter"]["id"]))
    validate_error(res, ApiErrorId.ERR_FITTER_NOT_CERTIFIED)


def test_confirm_mastectomy_uncertified_fitter_rejected(api):
    """PRD §3.2: "When fitting_type is POST_SURGICAL or MASTECTOMY, the fitter must
    have post_surgical_certified true, or the request is rejected with
    ERR_FITTER_NOT_CERTIFIED".

    Design: Difficulty/cross_entity_state_dependency/confirm_postsurgical_requires_certified_fitter
    """
    ctx = setup_booked_appointment(
        fitting_type="MASTECTOMY", post_surgical_certified=False, is_private=True,
        scheduled_start="2026-07-03T09:00:00Z",
    )
    res = api.confirm_appointment(ctx["appointment"]["id"], make_fitter_headers(ctx["fitter"]["id"]))
    validate_error(res, ApiErrorId.ERR_FITTER_NOT_CERTIFIED)


def test_confirm_postsurgical_nonprivate_room_rejected(api):
    """PRD §3.2: "and the room must have is_private true, or the request is rejected
    with ERR_ROOM_NOT_PRIVATE."

    Design: Corner/state_machines/confirm_postsurgical_nonprivate_room_returns_room_not_private
    """
    ctx = setup_booked_appointment(
        fitting_type="POST_SURGICAL", post_surgical_certified=True, is_private=False,
        scheduled_start="2026-07-10T09:00:00Z",
    )
    res = api.confirm_appointment(ctx["appointment"]["id"], make_fitter_headers(ctx["fitter"]["id"]))
    validate_error(res, ApiErrorId.ERR_ROOM_NOT_PRIVATE)


# ─── Precedence: safety (P9) beats scheduling constraint (P10) ────────────
def _safety_beats_constraint(api, second_type):
    cust = new_customer()
    fitter = new_fitter(post_surgical_certified=False)
    room_std = new_room(capacity=5, is_private=False)
    room_priv = new_room(capacity=5, is_private=True)
    appt_a = _book(api, cust["id"], fitter["id"], room_std["id"], "STANDARD", "2026-07-02T10:00:00Z")
    validate_success(api.confirm_appointment(appt_a["id"], make_fitter_headers(fitter["id"])), 200)
    appt_b = _book(api, cust["id"], fitter["id"], room_priv["id"], second_type, "2026-07-02T10:10:00Z")
    return api.confirm_appointment(appt_b["id"], make_fitter_headers(fitter["id"]))


def test_confirm_safety_error_precedes_double_booking_postsurgical(api):
    """PRD §2.9: "Ninth are business-safety checks (ERR_FITTER_NOT_CERTIFIED,
    ERR_ROOM_NOT_PRIVATE, ERR_ITEM_NOT_EXCHANGEABLE_HYGIENE). Tenth are
    scheduling-conflict checks (ERR_FITTER_DOUBLE_BOOKED, ERR_ROOM_AT_CAPACITY)."
    PRD §2.9: "Where a lower-priority failure and a higher-priority failure coexist,
    the higher-priority error is the one returned."

    Design: Difficulty/priority_pair_validation_conflict/confirm_safety_beats_constraint
    """
    res = _safety_beats_constraint(api, "POST_SURGICAL")
    validate_error(res, ApiErrorId.ERR_FITTER_NOT_CERTIFIED)


def test_confirm_safety_error_precedes_double_booking_mastectomy(api):
    """PRD §2.9: "Ninth are business-safety checks (ERR_FITTER_NOT_CERTIFIED,
    ERR_ROOM_NOT_PRIVATE, ERR_ITEM_NOT_EXCHANGEABLE_HYGIENE). Tenth are
    scheduling-conflict checks (ERR_FITTER_DOUBLE_BOOKED, ERR_ROOM_AT_CAPACITY)."
    PRD §2.9: "Where a lower-priority failure and a higher-priority failure coexist,
    the higher-priority error is the one returned."

    Design: Difficulty/priority_pair_validation_conflict/confirm_safety_beats_constraint
    """
    res = _safety_beats_constraint(api, "MASTECTOMY")
    validate_error(res, ApiErrorId.ERR_FITTER_NOT_CERTIFIED)


# ─── Fitter buffered overlap (queue A) ────────────────────────────────────
def test_fitter_buffered_overlap_within_buffer_rejected(api):
    """PRD §2.7: "Each appointment occupies a half-open interval that begins at its
    scheduled_start and ends at its scheduled_end extended by a turnover buffer of 15
    minutes."
    PRD §2.7: "A candidate appointment conflicts with an existing CONFIRMED or
    CHECKED_IN appointment on the same fitter_id when the candidate's buffered
    interval and the existing buffered interval overlap ... A conflict is rejected
    with ERR_FITTER_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/fitter_buffered_overlap_reject
    """
    cust = new_customer()
    fitter = new_fitter()
    room_a = new_room(capacity=5)
    room_b = new_room(capacity=5)
    appt_a = _book(api, cust["id"], fitter["id"], room_a["id"], "STANDARD", "2026-07-04T10:00:00Z")
    validate_success(api.confirm_appointment(appt_a["id"], make_fitter_headers(fitter["id"])), 200)
    appt_b = _book(api, cust["id"], fitter["id"], room_b["id"], "STANDARD", "2026-07-04T10:40:00Z")
    res = api.confirm_appointment(appt_b["id"], make_fitter_headers(fitter["id"]))
    validate_error(res, ApiErrorId.ERR_FITTER_DOUBLE_BOOKED)


def test_fitter_adjacent_at_buffer_boundary_allowed(api):
    """PRD §2.7: "Because the intervals are half-open, two appointments that merely
    touch at exactly the buffer boundary do not overlap."

    Design: Difficulty/resource_temporal_overlap/fitter_buffered_overlap_reject
    """
    cust = new_customer()
    fitter = new_fitter()
    room_a = new_room(capacity=5)
    room_b = new_room(capacity=5)
    appt_a = _book(api, cust["id"], fitter["id"], room_a["id"], "STANDARD", "2026-07-04T10:00:00Z")
    validate_success(api.confirm_appointment(appt_a["id"], make_fitter_headers(fitter["id"])), 200)
    # First appointment 10:00-10:30 buffered to 10:45; a second starting exactly 10:45 does not overlap.
    appt_b = _book(api, cust["id"], fitter["id"], room_b["id"], "STANDARD", "2026-07-04T10:45:00Z")
    confirmed = validate_success(
        api.confirm_appointment(appt_b["id"], make_fitter_headers(fitter["id"])), 200
    )
    assert confirmed["status"] == "CONFIRMED", confirmed


# ─── Room aggregate capacity (queue A) ────────────────────────────────────
def test_room_capacity_exceeded_rejected(api):
    """PRD §2.7: "The system counts existing CONFIRMED or CHECKED_IN appointments on
    the same room_id whose interval overlaps the candidate's interval ... If that
    count is greater than or equal to the room's capacity, the confirmation is
    rejected with ERR_ROOM_AT_CAPACITY".

    Design: Difficulty/resource_temporal_overlap/room_capacity_overlap_reject
    """
    cust = new_customer()
    fitter1 = new_fitter()
    fitter2 = new_fitter()
    room = new_room(capacity=1)
    appt_a = _book(api, cust["id"], fitter1["id"], room["id"], "STANDARD", "2026-07-05T10:00:00Z")
    validate_success(api.confirm_appointment(appt_a["id"], make_fitter_headers(fitter1["id"])), 200)
    appt_b = _book(api, cust["id"], fitter2["id"], room["id"], "STANDARD", "2026-07-05T10:00:00Z")
    res = api.confirm_appointment(appt_b["id"], make_fitter_headers(fitter2["id"]))
    validate_error(res, ApiErrorId.ERR_ROOM_AT_CAPACITY)


def test_room_capacity_admits_below_capacity(api):
    """PRD §2.7: "If that count is greater than or equal to the room's capacity, the
    confirmation is rejected with ERR_ROOM_AT_CAPACITY; capacity is honored only
    while the count stays strictly below it."

    Design: Difficulty/resource_temporal_overlap/room_capacity_overlap_reject
    """
    cust = new_customer()
    fitter1 = new_fitter()
    fitter2 = new_fitter()
    room = new_room(capacity=2)
    appt_a = _book(api, cust["id"], fitter1["id"], room["id"], "STANDARD", "2026-07-05T10:00:00Z")
    validate_success(api.confirm_appointment(appt_a["id"], make_fitter_headers(fitter1["id"])), 200)
    appt_b = _book(api, cust["id"], fitter2["id"], room["id"], "STANDARD", "2026-07-05T10:00:00Z")
    confirmed = validate_success(
        api.confirm_appointment(appt_b["id"], make_fitter_headers(fitter2["id"])), 200
    )
    assert confirmed["status"] == "CONFIRMED", confirmed
