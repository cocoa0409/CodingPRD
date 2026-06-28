"""Reservations, the waitlist, seat-count reconciliation, and freeze/cancel cascades.

Queue A: membership-cancel depth-3 cascade to waitlist promotion, session-cancel
depth-2 cascade, seat-count invariant, punch-balance invariant.
Queue B: cancel-already-cancelled guard, new session initial state, completed-session
terminal lockdown, waitlist creation when full, filtered list, seats reconciliation,
immediate visibility of punch decrement.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    make_member_headers, make_coach_headers,
    set_clock, create_coach, create_track, create_unlimited_plan,
    create_punch_plan, register_member, create_session,
    create_active_membership, reserve, setup_reserved_seat,
    setup_full_session_with_waitlist, setup_drop_in_reserved_seat,
)

BOX = TEST_USERS["box_manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


# --------------------------------------------------------------------------
# Queue A — transitive_cascade / membership_cancel_cascade_depth3_to_waitlist_promotion
# --------------------------------------------------------------------------

def test_membership_cancel_cascades_to_waitlist_promotion(api):
    """PRD §3.3: "every future `RESERVED` reservation of the membership is transitioned from `RESERVED` to `CANCELLED`, decrementing each affected session's `seats_reserved` and promoting that session's waitlist head."
    PRD §3.4: "Promotion sets that reservation's `status` to `RESERVED` and clears its `waitlist_position` to null, increments the session's `seats_reserved` by one and decrements its `waitlist_count` by one".

    Design: Difficulty/transitive_cascade/membership_cancel_cascade_depth3_to_waitlist_promotion
    """
    s = setup_full_session_with_waitlist(
        session_starts_at="2026-06-10T18:00:00Z", clock_before="2026-06-01T00:00:00Z"
    )
    hold = s["hold"]
    wait = s["wait"]

    resp = api.cancel_membership(hold["membership"]["id"],
                                 make_member_headers(hold["member"]["id"]))
    validate_success(resp)

    rv_hold = validate_success(api.get_reservation(hold["reservation"]["id"], BOX))
    assert rv_hold["status"] == "CANCELLED"

    rv_wait = validate_success(api.get_reservation(wait["reservation"]["id"], BOX))
    assert rv_wait["status"] == "RESERVED"
    assert rv_wait["waitlist_position"] is None

    session = validate_success(api.get_session(s["session"]["id"], BOX))
    assert session["seats_reserved"] == 1
    assert session["waitlist_count"] == 0


def test_membership_cancel_transitions_pending_and_cancels_held_reservation(api):
    """PRD §3.3: "Cancellation does not delete the membership immediately — it moves the membership into `CANCEL_PENDING".
    PRD §3.3: "every future `RESERVED` reservation of the membership is transitioned from `RESERVED` to `CANCELLED`, decrementing each affected session's `seats_reserved".

    Design: Difficulty/transitive_cascade/membership_cancel_cascade_depth3_to_waitlist_promotion
    """
    s = setup_full_session_with_waitlist(
        session_starts_at="2026-06-10T18:00:00Z", clock_before="2026-06-01T00:00:00Z"
    )
    hold = s["hold"]
    resp = api.cancel_membership(hold["membership"]["id"],
                                 make_member_headers(hold["member"]["id"]))
    ms_after = validate_success(resp)
    assert ms_after["status"] == "CANCEL_PENDING"

    rv_hold = validate_success(api.get_reservation(hold["reservation"]["id"], BOX))
    assert rv_hold["status"] == "CANCELLED"


# --------------------------------------------------------------------------
# Queue A — transitive_cascade / session_cancel_cascade_depth2_reservation_release
# --------------------------------------------------------------------------

def test_session_cancel_cascades_to_reservation_cancel_and_zeroes_seats(api):
    """PRD §3.5: "A box-initiated session cancellation moves the session from `SCHEDULED` to `CANCELLED` and always refunds, regardless of the late-cancel window: every `RESERVED` reservation on the session is transitioned from `RESERVED` to `CANCELLED` with full punch-restore and drop-in-fee refund".
    PRD §3.5: "The session's `seats_reserved` and `waitlist_count` are both set to 0 and its `version` increments."

    Design: Difficulty/transitive_cascade/session_cancel_cascade_depth2_reservation_release
    """
    s = setup_reserved_seat(session_starts_at="2026-06-10T18:00:00Z",
                            clock_before="2026-06-01T00:00:00Z", capacity=3)
    coach_id = s["coach"]["id"]

    resp = api.cancel_session(s["session"]["id"], make_coach_headers(coach_id))
    session = validate_success(resp)
    assert session["status"] == "CANCELLED"

    rv = validate_success(api.get_reservation(s["reservation"]["id"], BOX))
    assert rv["status"] == "CANCELLED"
    assert session["seats_reserved"] == 0


def test_session_cancel_drop_in_refunds_fee_regardless_of_window(api):
    """PRD §3.5: "A box-initiated session cancellation moves the session from `SCHEDULED` to `CANCELLED` and always refunds, regardless of the late-cancel window: every `RESERVED` reservation on the session is transitioned from `RESERVED` to `CANCELLED` with full punch-restore and drop-in-fee refund".

    Design: Difficulty/transitive_cascade/session_cancel_cascade_depth2_reservation_release
    """
    # Visiting athlete holds a DROP_IN RESERVED seat charged 2500; cancel the
    # session well inside the 12h late-cancel window — box cancel still refunds.
    s = setup_drop_in_reserved_seat(session_starts_at="2026-06-10T18:00:00Z",
                                    clock_before="2026-06-01T00:00:00Z",
                                    drop_in_fee_cents=2500)
    set_clock("2026-06-10T17:00:00Z")  # only 1h before start (late window)
    resp = api.cancel_session(s["session"]["id"], make_coach_headers(s["coach"]["id"]))
    session = validate_success(resp)
    assert session["status"] == "CANCELLED"

    rv = validate_success(api.get_reservation(s["reservation"]["id"], BOX))
    assert rv["status"] == "CANCELLED"
    assert rv["drop_in_fee_charged_cents"] == 0


# --------------------------------------------------------------------------
# Queue A — compensating_invariant / seat_count_invariant_reserve_then_timely_cancel
# --------------------------------------------------------------------------

def test_seat_count_invariant_reserve_then_timely_cancel(api):
    """PRD §3.5: "Cancelling a `RESERVED` reservation transitions it from `RESERVED` to `CANCELLED`, decrements the session's `seats_reserved` by one".
    PRD §2.5: "the system never leaves a counter drifted from the rows it counts."

    Design: Difficulty/compensating_invariant/seat_count_invariant_reserve_then_timely_cancel
    """
    s = setup_reserved_seat(session_starts_at="2026-06-10T18:00:00Z",
                            clock_before="2026-06-05T00:00:00Z", capacity=2)
    # clock is 2026-06-05, > 12h before 2026-06-10 start: timely cancel.
    resp = api.cancel_reservation(s["reservation"]["id"],
                                  make_member_headers(s["member"]["id"]))
    rv = validate_success(resp)
    assert rv["status"] == "CANCELLED"

    session = validate_success(api.get_session(s["session"]["id"], BOX))
    assert session["seats_reserved"] == 0
    assert session["waitlist_count"] == 0


def test_seat_count_increments_to_one_after_reserve(api):
    """PRD §3.4: "Otherwise the reservation is created `RESERVED`: the session's `seats_reserved` increments".
    PRD §2.5: "A `ClassSession` exposes `seats_reserved`, the live count of its reservations in `RESERVED` status".

    Design: Difficulty/compensating_invariant/seat_count_invariant_reserve_then_timely_cancel
    """
    s = setup_reserved_seat(session_starts_at="2026-06-10T18:00:00Z",
                            clock_before="2026-06-05T00:00:00Z", capacity=2)
    # seats_reserved was captured == 1 immediately after the reserve.
    assert s["session"]["seats_reserved"] == 1


# --------------------------------------------------------------------------
# Queue A — compensating_invariant / punch_balance_invariant_reserve_then_timely_cancel
# --------------------------------------------------------------------------

def test_punch_balance_invariant_reserve_then_timely_cancel(api):
    """PRD §3.5: "If the gap is at least 12 hours the cancel is timely — the punch is restored (the membership's `punches_remaining` is increased by one when `punch_consumed` was true)".

    Design: Difficulty/compensating_invariant/punch_balance_invariant_reserve_then_timely_cancel
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    plan = create_punch_plan(punch_count=5, requires_foundations=False)
    set_clock("2026-06-05T00:00:00Z")
    session = create_session(track["id"], coach["id"], "2026-06-10T18:00:00Z", capacity=5)
    member = register_member()
    ms = create_active_membership(member["id"], plan["id"])
    rv = reserve(session["id"], member["id"], session["version"],
                 membership_id=ms["id"], reservation_kind="MEMBERSHIP")

    # timely cancel (clock at 2026-06-05, >12h before start)
    resp = api.cancel_reservation(rv["id"], make_member_headers(member["id"]))
    rv_after = validate_success(resp)
    assert rv_after["status"] == "CANCELLED"

    ms_after = validate_success(api.get_membership(ms["id"], BOX))
    assert ms_after["punches_remaining"] == 5


def test_punch_decrements_on_reserve_before_cancel(api):
    """PRD §3.4: "for a `PUNCH`-plan `MEMBERSHIP` reservation the membership's `punches_remaining` is decremented by one and `punch_consumed` is set true".

    Design: Difficulty/compensating_invariant/punch_balance_invariant_reserve_then_timely_cancel
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    plan = create_punch_plan(punch_count=5, requires_foundations=False)
    set_clock("2026-06-05T00:00:00Z")
    session = create_session(track["id"], coach["id"], "2026-06-10T18:00:00Z", capacity=5)
    member = register_member()
    ms = create_active_membership(member["id"], plan["id"])
    rv = reserve(session["id"], member["id"], session["version"],
                 membership_id=ms["id"], reservation_kind="MEMBERSHIP")

    rv_after = validate_success(api.get_reservation(rv["id"], BOX))
    assert rv_after["punch_consumed"] is True
    ms_after = validate_success(api.get_membership(ms["id"], BOX))
    assert ms_after["punches_remaining"] == 4


# --------------------------------------------------------------------------
# Queue B — state_machines / cancel_reservation_already_cancelled_returns_invalid_state
# --------------------------------------------------------------------------

def test_cancel_reservation_twice_returns_invalid_state(api):
    """PRD §3.5: "Cancellation is permitted only while the reservation is `RESERVED` or `WAITLISTED` and the session is `SCHEDULED`; otherwise `ERR_INVALID_STATE` applies."

    Design: Corner/state_machines/cancel_reservation_already_cancelled_returns_invalid_state
    """
    s = setup_reserved_seat(session_starts_at="2026-06-10T18:00:00Z",
                            clock_before="2026-06-01T00:00:00Z", capacity=3)
    hdr = make_member_headers(s["member"]["id"])
    validate_success(api.cancel_reservation(s["reservation"]["id"], hdr))
    resp = api.cancel_reservation(s["reservation"]["id"], hdr)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    session = validate_success(api.get_session(s["session"]["id"], BOX))
    assert session["seats_reserved"] == 0


# --------------------------------------------------------------------------
# Queue B — state_machines / new_session_starts_in_scheduled_initial_state
# --------------------------------------------------------------------------

def test_new_session_starts_scheduled_with_zero_counters(api):
    """PRD §3.4: "A new session is born `SCHEDULED` with `seats_reserved` and `waitlist_count` both 0."

    Design: Corner/state_machines/new_session_starts_in_scheduled_initial_state
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    set_clock("2026-06-01T00:00:00Z")
    resp = api.create_session(
        {"track_id": track["id"], "coach_id": coach["id"],
         "starts_at": "2026-06-10T18:00:00Z", "duration_minutes": 60, "capacity": 5},
        make_coach_headers(coach["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED"
    assert data["seats_reserved"] == 0
    assert data["waitlist_count"] == 0


# --------------------------------------------------------------------------
# Queue B — state_machines / complete_session_terminal_lockdown_no_recancel
# --------------------------------------------------------------------------

def test_cancel_completed_session_returns_invalid_state(api):
    """PRD §3.5: "A `Coach` (or a `BoxManager`) may also cancel a scheduled session outright, permitted only from `SCHEDULED` (otherwise `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/complete_session_terminal_lockdown_no_recancel
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    set_clock("2026-06-01T00:00:00Z")
    session = create_session(track["id"], coach["id"], "2026-06-02T18:00:00Z", capacity=3)
    set_clock("2026-06-02T18:30:00Z")
    validate_success(api.complete_session(session["id"], {"attendance": {}},
                                          make_coach_headers(coach["id"])))
    resp = api.cancel_session(session["id"], make_coach_headers(coach["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------
# Queue B — endpoints / waitlist_create_when_session_full
# --------------------------------------------------------------------------

def test_reserve_full_session_creates_waitlisted_entry(api):
    """PRD §3.4: "If the session is full — its `seats_reserved` equals its `capacity` — and the session is `SCHEDULED`, the reservation is created directly into `WAITLISTED` rather than `RESERVED`: it is assigned a `waitlist_position` equal to the session's current `waitlist_count` plus one, the session's `waitlist_count` increments, and crucially no punch is consumed and no drop-in fee is charged while waitlisted."

    Design: Corner/endpoints/waitlist_create_when_session_full
    """
    s = setup_full_session_with_waitlist(
        session_starts_at="2026-06-10T18:00:00Z", clock_before="2026-06-01T00:00:00Z"
    )
    rv_wait = validate_success(api.get_reservation(s["wait"]["reservation"]["id"], BOX))
    assert rv_wait["status"] == "WAITLISTED"
    assert rv_wait["waitlist_position"] == 1

    session = validate_success(api.get_session(s["session"]["id"], BOX))
    assert session["waitlist_count"] == 1
    assert session["seats_reserved"] == 1


# --------------------------------------------------------------------------
# Queue B — endpoints / filtered_list_reservations_by_session_returns_array
# --------------------------------------------------------------------------

def test_filtered_list_reservations_by_session(api):
    """PRD §4 (GET /box/reservations): "List reservations (filter by session_id,
    member_id, membership_id, status)".
    PRD §2.2: "The `response_type` is either"object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/filtered_list_reservations_by_session_returns_array
    """
    s = setup_reserved_seat(session_starts_at="2026-06-10T18:00:00Z",
                            clock_before="2026-06-01T00:00:00Z", capacity=5)
    resp = api.list_reservations(BOX, params={"session_id": s["session"]["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["id"] == s["reservation"]["id"]
    assert data[0]["status"] == "RESERVED"


# --------------------------------------------------------------------------
# Queue B — cross_cutting / derived_field_seats_reserved_reconciled_after_create
# --------------------------------------------------------------------------

def test_seats_reserved_reconciled_through_create_and_cancel(api):
    """PRD §2.5: "A `ClassSession` exposes `seats_reserved`, the live count of its reservations in `RESERVED` status, and `waitlist_count`, the live count of its reservations in `WAITLISTED` status; both are recomputed on every reservation create, cancel, no-show, completion, and waitlist promotion that touches the session."

    Design: Corner/cross_cutting_complexity_layers/derived_field_seats_reserved_reconciled_after_create
    """
    s = setup_reserved_seat(session_starts_at="2026-06-10T18:00:00Z",
                            clock_before="2026-06-05T00:00:00Z", capacity=3)
    assert s["session"]["seats_reserved"] == 1  # captured after create

    api.cancel_reservation(s["reservation"]["id"], make_member_headers(s["member"]["id"]))
    session = validate_success(api.get_session(s["session"]["id"], BOX))
    assert session["seats_reserved"] == 0


# --------------------------------------------------------------------------
# Queue B — consistency_model / immediate_visibility_seats_in_reserve_response_chain
# --------------------------------------------------------------------------

def test_punch_decrement_immediately_visible_on_membership_get(api):
    """PRD §3.4: "for a `PUNCH`-plan `MEMBERSHIP` reservation the membership's `punches_remaining` is decremented by one and `punch_consumed` is set true".
    PRD §2.5: "that mutation is applied to the owning resource atomically within
    the same request".

    Design: Corner/consistency_model/immediate_visibility_seats_in_reserve_response_chain
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    plan = create_punch_plan(punch_count=5, requires_foundations=False)
    set_clock("2026-06-05T00:00:00Z")
    session = create_session(track["id"], coach["id"], "2026-06-10T18:00:00Z", capacity=5)
    member = register_member()
    ms = create_active_membership(member["id"], plan["id"])
    rv = reserve(session["id"], member["id"], session["version"],
                 membership_id=ms["id"], reservation_kind="MEMBERSHIP")

    rv_after = validate_success(api.get_reservation(rv["id"], BOX))
    assert rv_after["punch_consumed"] is True

    ms_after = validate_success(api.get_membership(ms["id"], make_member_headers(member["id"])))
    assert ms_after["punches_remaining"] == 4
