"""Invalid-state transitions, timing windows, capacity, cross-entity state gates,
maintenance guards, and validation-priority conflicts.

Covers difficulty queue rules priority_pair_validation_conflict /
cross_entity_state_dependency / boundary_precision_check (queue side) and the
corner state_machines / validations / errors sections.
"""
import pytest
from test_helpers import (
    validate_error, ApiErrorId,
    setup_base, create_held_reservation, confirm_reservation,
    create_confirmed_reservation, create_checked_in_reservation,
    create_song, queue_song, set_clock, check_in_reservation,
    get_room_version, get_reservation,
    make_customer_headers, make_front_desk_headers, make_venue_manager_headers,
    create_group_package,
)

FD = make_front_desk_headers()
VM = make_venue_manager_headers()


def _cust(c):
    return make_customer_headers(c["id"])


# ─── Invalid-state transitions ────────────────────────────────────
def test_confirm_already_confirmed_invalid_state(api):
    """PRD §3.3: "Confirming requires the reservation to be in `HELD` status; confirming
    anything else is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/confirm_from_already_confirmed_returns_invalid_state
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-02T10:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_confirmed_reservation(venue, room, customer,
                                       "2026-08-02T20:00:00.000Z", "2026-08-02T22:00:00.000Z",
                                       confirm_clock_utc=None, party_size=4)
    validate_error(api.confirm_reservation(res["id"], _cust(customer)),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_terminal_cancelled_cannot_cancel_again(api):
    """PRD §3.7: "Both `EXPIRED` and `NO_SHOW`, like `CLOSED` and `CANCELLED`, are
    terminal states from which no further transition is possible."
    PRD §2.8: "the target resource must be in a state from which the requested transition
    is legal, failing which the request is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_cancelled_reservation_cannot_cancel_again
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-03T10:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_held_reservation(venue, room, customer,
                                  "2026-08-03T20:00:00.000Z", "2026-08-03T22:00:00.000Z",
                                  party_size=4)
    from test_helpers import validate_success
    validate_success(api.cancel_reservation(res["id"], _cust(customer)), 200)
    validate_error(api.cancel_reservation(res["id"], _cust(customer)),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_void_already_voided_invalid_state(api):
    """PRD §3.8: "Voiding a line that is not `PLACED` is rejected with `ERR_INVALID_STATE`."

    Design: Corner/errors/void_already_voided_fborder_invalid_state
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-20T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_checked_in_reservation(venue, room, customer,
                                        "2026-08-20T20:00:00.000Z", "2026-08-20T22:00:00.000Z",
                                        checkin_clock_utc="2026-08-20T20:00:00.000Z")
    from test_helpers import add_fb_order, void_fb_order
    fb = add_fb_order(res, customer, unit_price_cents=1000, quantity=1, description="Item")
    void_fb_order(fb["id"])
    validate_error(api.void_fb_order(fb["id"], FD), ApiErrorId.ERR_INVALID_STATE.value)


def test_play_on_empty_queue_invalid_state(api):
    """PRD §3.6: "Playing requires the entry to be `PENDING` ... playing a non-`PENDING`
    entry, or playing when the parent session is not `CHECKED_IN`, is rejected with
    `ERR_INVALID_STATE`."

    After the single entry is PLAYED, a second play on the now-PLAYED entry is rejected
    ERR_INVALID_STATE — the zero-PENDING-count edge.

    Design: Difficulty/boundary_precision_check/play_on_empty_queue_zero_count_edge
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-17T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    song = create_song(venue["id"], title="Solo", artist="S")
    res = create_checked_in_reservation(venue, room, customer,
                                        "2026-07-17T20:00:00.000Z", "2026-07-17T22:00:00.000Z",
                                        checkin_clock_utc="2026-07-17T20:00:00.000Z")
    q = queue_song(res, customer, song["id"], priority=10)
    from test_helpers import validate_success
    validate_success(api.play_queue_entry(q["id"], FD), 200)
    validate_error(api.play_queue_entry(q["id"], FD), ApiErrorId.ERR_INVALID_STATE.value)


# ─── Cross-entity state dependency ────────────────────────────────
def test_checkin_blocked_when_room_out_of_service(api):
    """PRD §3.4: "requires the assigned room to be `AVAILABLE` rather than `OCCUPIED` or
    `OUT_OF_SERVICE`."

    A CONFIRMED reservation whose room was toggled OUT_OF_SERVICE cannot check in:
    ERR_INVALID_STATE, reservation stays CONFIRMED.

    Design: Difficulty/cross_entity_state_dependency/checkin_blocked_when_room_out_of_service
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-18T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_confirmed_reservation(venue, room, customer,
                                       "2026-07-18T20:00:00.000Z", "2026-07-18T22:00:00.000Z",
                                       confirm_clock_utc=None, party_size=6)
    from test_helpers import get_success_data
    get_success_data(api.room_maintenance(room["id"], {"target": "OUT_OF_SERVICE"}, VM))
    set_clock(venue["id"], "2026-07-18T20:00:00.000Z")
    validate_error(api.check_in_reservation(res["id"], FD), ApiErrorId.ERR_INVALID_STATE.value)
    assert get_reservation(res["id"])["status"] == "CONFIRMED"


def test_play_blocked_when_reservation_not_checked_in(api):
    """PRD §3.6: "Playing requires the entry to be `PENDING`, requires the parent
    reservation to be `CHECKED_IN` ... playing when the parent session is not
    `CHECKED_IN`, is rejected with `ERR_INVALID_STATE`."

    Head entry on a CONFIRMED (not yet CHECKED_IN) reservation: play -> ERR_INVALID_STATE,
    entry stays PENDING.

    Design: Difficulty/cross_entity_state_dependency/queue_play_blocked_when_reservation_not_checked_in
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-19T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    song = create_song(venue["id"], title="Early", artist="E")
    res = create_confirmed_reservation(venue, room, customer,
                                       "2026-07-19T20:00:00.000Z", "2026-07-19T22:00:00.000Z",
                                       confirm_clock_utc=None, party_size=6)
    q = queue_song(res, customer, song["id"], priority=10)
    validate_error(api.play_queue_entry(q["id"], FD), ApiErrorId.ERR_INVALID_STATE.value)
    from test_helpers import get_queue_entry
    assert get_queue_entry(q["id"])["status"] == "PENDING"


def test_room_maintenance_blocked_when_occupied(api):
    """PRD §3.1: "Taking a room out of service moves it from `AVAILABLE` to
    `OUT_OF_SERVICE`, and this is only permitted while the room is `AVAILABLE`; an
    attempt to take an `OCCUPIED` room out of service is rejected with
    `ERR_ROOM_NOT_AVAILABLE`."

    Design: Corner/state_machines/room_maintenance_blocked_when_occupied_invalid_transition
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-05T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    create_checked_in_reservation(venue, room, customer,
                                  "2026-08-05T20:00:00.000Z", "2026-08-05T22:00:00.000Z",
                                  checkin_clock_utc="2026-08-05T20:00:00.000Z")
    validate_error(api.room_maintenance(room["id"], {"target": "OUT_OF_SERVICE"}, VM),
                   ApiErrorId.ERR_ROOM_NOT_AVAILABLE.value)


# ─── Timing windows ───────────────────────────────────────────────
def test_confirm_after_slot_start_timing_window(api):
    """PRD §3.3: "It also requires that the slot has not already started — the current
    venue time must be strictly before `slot_start_utc`, and confirming a slot whose
    start has already passed is rejected with `ERR_TIMING_WINDOW`."

    Design: Corner/validations/confirm_after_slot_start_timing_window_rejected
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-13T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_held_reservation(venue, room, customer,
                                  "2026-08-13T20:00:00.000Z", "2026-08-13T22:00:00.000Z",
                                  party_size=4)
    set_clock(venue["id"], "2026-08-13T20:01:00.000Z")
    validate_error(api.confirm_reservation(res["id"], _cust(customer)),
                   ApiErrorId.ERR_TIMING_WINDOW.value)


def test_checkin_after_grace_window_timing(api):
    """PRD §3.4: "Check-in ... requires the current venue time to be no later than
    `slot_start_utc` plus the venue's `grace_minutes` — that is, within the grace window
    — failing which the attempt is rejected with `ERR_TIMING_WINDOW`".

    Confirmed; clock 20:16 (grace 15 -> deadline 20:15); manual check-in -> TIMING_WINDOW.

    Design: Corner/validations/checkin_after_grace_window_timing_rejected
    """
    base = setup_base(
        venue_overrides={"grace_minutes": 15},
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-14T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_confirmed_reservation(venue, room, customer,
                                       "2026-08-14T20:00:00.000Z", "2026-08-14T22:00:00.000Z",
                                       confirm_clock_utc=None, party_size=4)
    set_clock(venue["id"], "2026-08-14T20:16:00.000Z")
    validate_error(api.check_in_reservation(res["id"], FD), ApiErrorId.ERR_TIMING_WINDOW.value)


# ─── Capacity ─────────────────────────────────────────────────────
def test_create_party_over_capacity(api):
    """PRD §3.3: "The `party_size` must be at least 1 and must not exceed the capacity
    of the reservation's room type; a party larger than the room allows is rejected with
    `ERR_CAPACITY_EXCEEDED`."

    SMALL capacity 4, party_size 10, no overlap -> ERR_CAPACITY_EXCEEDED.

    Design: Corner/validations/confirm_party_over_capacity_rejected
    """
    base = setup_base(
        room_type_overrides={"name": "SMALL", "capacity": 4, "base_hourly_rate_cents": 3500},
        clock_utc="2026-08-15T10:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    room_v = get_room_version(room["id"])
    from test_helpers import create_reservation_payload
    payload = create_reservation_payload(
        venue["id"], room["id"], customer["id"], room_v,
        "2026-08-15T20:00:00.000Z", "2026-08-15T22:00:00.000Z", party_size=10,
    )
    validate_error(api.create_reservation(payload, _cust(customer)),
                   ApiErrorId.ERR_CAPACITY_EXCEEDED.value)


# ─── Room-type mismatch ───────────────────────────────────────────
def test_package_room_type_mismatch(api):
    """PRD §3.3: "when a package is named — the package's `included_room_type_id` must
    equal the room's `room_type_id`; any of these mismatches is rejected with
    `ERR_ROOM_TYPE_MISMATCH`."

    Booking a SMALL room with a package built for LARGE -> ERR_ROOM_TYPE_MISMATCH.

    Design: Corner/validations/room_type_mismatch_package_room_type_rejected
    """
    from test_helpers import (create_venue, create_room_type, create_room,
                              create_customer, set_clock as _set_clock,
                              create_reservation_payload)
    v = create_venue()
    rt_small = create_room_type(v["id"], name="SMALL", capacity=4, base_hourly_rate_cents=3500)
    rt_large = create_room_type(v["id"], name="LARGE", capacity=12, base_hourly_rate_cents=6000)
    room = create_room(v["id"], rt_small["id"], label="Small 1")
    pkg = create_group_package(v["id"], rt_large["id"], name="Big",
                               flat_price_cents=20000, included_hours=2.0)
    cust = create_customer()
    _set_clock(v["id"], "2026-08-12T10:00:00.000Z")
    room_v = get_room_version(room["id"])
    payload = create_reservation_payload(
        v["id"], room["id"], cust["id"], room_v,
        "2026-08-12T20:00:00.000Z", "2026-08-12T22:00:00.000Z",
        party_size=2, group_package_id=pkg["id"],
    )
    validate_error(api.create_reservation(payload, _cust(cust)),
                   ApiErrorId.ERR_ROOM_TYPE_MISMATCH.value)


# ─── Validation priority conflicts ────────────────────────────────
def test_confirm_invalid_state_beats_timing_window(api):
    """PRD §2.8: "Fifth, state: the target resource must be in a state from which the
    requested transition is legal, failing which the request is rejected with
    `ERR_INVALID_STATE`."
    PRD §2.8: "where two checks could both fire on the same request, the lower-numbered
    one is the one that is returned."

    An already-CONFIRMED reservation whose slot_start has also passed violates both state
    (5) and timing (7); the lower-numbered state check wins -> ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/confirm_invalid_state_beats_timing_window
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-07-14T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_confirmed_reservation(venue, room, customer,
                                       "2026-07-14T20:00:00.000Z", "2026-07-14T22:00:00.000Z",
                                       confirm_clock_utc=None, party_size=6)
    set_clock(venue["id"], "2026-07-14T20:30:00.000Z")
    err = validate_error(api.confirm_reservation(res["id"], _cust(customer)),
                         ApiErrorId.ERR_INVALID_STATE.value)
    assert err["error_id"] == "ERR_INVALID_STATE"


def test_capacity_exceeded_beats_double_booked(api):
    """PRD §2.8: "Eighth is the capacity check, which yields `ERR_CAPACITY_EXCEEDED`.
    ... Tenth is the room double-booking overlap check, which yields
    `ERR_ROOM_DOUBLE_BOOKED`."
    PRD §2.8: "where two checks could both fire on the same request, the lower-numbered
    one is the one that is returned."

    A create that both exceeds capacity (8) and overlaps an active booking (10) returns
    the lower-numbered capacity error.

    Design: Difficulty/priority_pair_validation_conflict/create_capacity_exceeded_beats_double_booked
    """
    base = setup_base(
        room_type_overrides={"name": "SMALL", "capacity": 4, "base_hourly_rate_cents": 3500},
        clock_utc="2026-07-15T10:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    create_held_reservation(venue, room, customer,
                            "2026-07-15T20:00:00.000Z", "2026-07-15T22:00:00.000Z",
                            party_size=2)
    room_v = get_room_version(room["id"])
    from test_helpers import create_reservation_payload
    payload = create_reservation_payload(
        venue["id"], room["id"], customer["id"], room_v,
        "2026-07-15T21:00:00.000Z", "2026-07-15T23:00:00.000Z", party_size=10,
    )
    validate_error(api.create_reservation(payload, _cust(customer)),
                   ApiErrorId.ERR_CAPACITY_EXCEEDED.value)
