"""Retreat capacity cycle, bed/seat boundaries, room-kind gating, occupancy conservation."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    set_clock, setup_published_retreat, setup_booking, setup_booking_deposit_paid,
    new_guest, new_room, new_shuttle, get_room, get_shuttle,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.factories import create_booking_payload
from test_helpers.test_users import make_guest_headers

_OP = TEST_USERS["operator_headers"]


def _current_version(api, retreat_id):
    return validate_success(api.get_retreat(retreat_id, _OP), 200)["version"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / retreat_full_publish_capacity_cycle
# ---------------------------------------------------------------------------
def test_booking_to_capacity_flips_retreat_to_full(api):
    """PRD §3.1: "When a booking pushes `reserved_count` up to exactly `capacity`, the server transitions the retreat from `PUBLISHED` to `FULL` at the end of that booking."

    Design: Difficulty/non_linear_state_machine/retreat_full_publish_capacity_cycle
    """
    ctx = setup_booking(api, party_size=2,
                        retreat_overrides={"capacity": 2}, room_overrides={"bed_count": 2})
    retreat = validate_success(api.get_retreat(ctx["retreat"]["id"], _OP), 200)
    assert retreat["status"] == "FULL"
    assert retreat["reserved_count"] == 2


def test_cancel_returns_full_retreat_to_published(api):
    """PRD §3.1: "when a cancellation releases seats so that `reserved_count` falls back below `capacity`, the server transitions the retreat from `FULL` back to `PUBLISHED`."

    Design: Difficulty/non_linear_state_machine/retreat_full_publish_capacity_cycle
    """
    ctx = setup_booking(api, party_size=2,
                        retreat_overrides={"capacity": 2}, room_overrides={"bed_count": 2})
    validate_success(api.cancel_booking(ctx["booking"]["id"], ctx["guest_headers"]), 200)
    retreat = validate_success(api.get_retreat(ctx["retreat"]["id"], _OP), 200)
    assert retreat["status"] == "PUBLISHED"
    assert retreat["reserved_count"] == 0


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / room_bed_capacity_exact_fill_then_reject
# ---------------------------------------------------------------------------
def test_booking_exceeding_room_beds_rejected(api):
    """PRD §3.2: "the room's `reserved_beds` plus the new `party_size` must not exceed the room's `bed_count` (otherwise `ERR_ROOM_FULL`, HTTP 409)."

    Design: Difficulty/boundary_precision_check/room_bed_capacity_exact_fill_then_reject
    """
    ctx = setup_booking(api, party_size=2,
                        retreat_overrides={"capacity": 20}, room_overrides={"bed_count": 2})
    room = get_room(api, ctx["retreat"]["id"], ctx["room"]["id"])
    assert room["reserved_beds"] == 2
    rv2 = _current_version(api, ctx["retreat"]["id"])
    payload = create_booking_payload(
        ctx["retreat"]["id"], ctx["guest"]["id"], ctx["room"]["id"], 1, rv2)
    resp = api.create_booking(payload, ctx["guest_headers"])
    validate_error(resp, ApiErrorId.ERR_ROOM_FULL.value)


def test_booking_filling_room_exactly_to_bed_count_succeeds(api):
    """PRD §3.2: "the room's `reserved_beds` plus the new `party_size` must not exceed the room's `bed_count` (otherwise `ERR_ROOM_FULL`, HTTP 409)."

    Design: Difficulty/boundary_precision_check/room_bed_capacity_exact_fill_then_reject
    """
    ctx = setup_booking(api, party_size=2,
                        retreat_overrides={"capacity": 20}, room_overrides={"bed_count": 2})
    assert ctx["booking"]["status"] == "PENDING_DEPOSIT"
    room = get_room(api, ctx["retreat"]["id"], ctx["room"]["id"])
    assert room["reserved_beds"] == 2  # exact fill 2 == bed_count 2 is allowed


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / bed_occupancy_conserved_on_book_then_cancel
# ---------------------------------------------------------------------------
def test_booking_raises_reserved_beds(api):
    """PRD §2.8: "A lodging room's `reserved_beds` is the sum of `party_size` across bookings on that room in those same four statuses."

    Design: Difficulty/compensating_invariant/bed_occupancy_conserved_on_book_then_cancel
    """
    ctx = setup_booking(api, party_size=2, room_overrides={"bed_count": 4})
    room = get_room(api, ctx["retreat"]["id"], ctx["room"]["id"])
    assert room["reserved_beds"] == 2


def test_book_then_cancel_conserves_bed_and_seat_counters(api):
    """PRD §3.7: "the booking's `party_size` is subtracted from the room's `reserved_beds` and from the retreat's `reserved_count`"

    Design: Difficulty/compensating_invariant/bed_occupancy_conserved_on_book_then_cancel
    """
    ctx = setup_booking(api, party_size=2, room_overrides={"bed_count": 4})
    validate_success(api.cancel_booking(ctx["booking"]["id"], ctx["guest_headers"]), 200)
    room = get_room(api, ctx["retreat"]["id"], ctx["room"]["id"])
    retreat = validate_success(api.get_retreat(ctx["retreat"]["id"], _OP), 200)
    assert room["reserved_beds"] == 0
    assert retreat["reserved_count"] == 0


# ---------------------------------------------------------------------------
# Corner: validations / corner_retreat_capacity_full_rejected
# ---------------------------------------------------------------------------
def test_booking_exceeding_retreat_capacity_rejected(api):
    """PRD §3.2: "the retreat's `reserved_count` plus the new `party_size` must not exceed the retreat's `capacity` (otherwise `ERR_RETREAT_FULL`, HTTP 409)."

    Design: Corner/validations/corner_retreat_capacity_full_rejected
    """
    base = setup_published_retreat(
        api, retreat_overrides={"capacity": 3},
        room_overrides={"bed_count": 2, "label": "R1"})
    room2 = new_room(api, base["retreat"]["id"], bed_count=4, label="R2")
    guest = new_guest(api)
    gh = make_guest_headers(guest["id"])
    b1 = create_booking_payload(base["retreat"]["id"], guest["id"], base["room"]["id"], 2, base["version"])
    validate_success(api.create_booking(b1, gh), 201)  # reserved_count=2, still PUBLISHED
    rv2 = _current_version(api, base["retreat"]["id"])
    b2 = create_booking_payload(base["retreat"]["id"], guest["id"], room2["id"], 2, rv2)
    resp = api.create_booking(b2, gh)
    validate_error(resp, ApiErrorId.ERR_RETREAT_FULL.value)


# ---------------------------------------------------------------------------
# Corner: validations / corner_book_common_room_kind_mismatch_rejected
# ---------------------------------------------------------------------------
def test_booking_common_room_rejected(api):
    """PRD §3.2: "the chosen room must be of kind `LODGING` (otherwise `ERR_ROOM_KIND_MISMATCH`, HTTP 422)."

    Design: Corner/validations/corner_book_common_room_kind_mismatch_rejected
    """
    set_clock(api, DEFAULT_CLOCK)
    base = setup_published_retreat(api, room_overrides={"bed_count": 4, "label": "Lodge"},
                                   set_default_clock=False)
    common = new_room(api, base["retreat"]["id"], kind="COMMON", bed_count=0, label="Hall")
    guest = new_guest(api)
    gh = make_guest_headers(guest["id"])
    payload = create_booking_payload(base["retreat"]["id"], guest["id"], common["id"], 1, base["version"])
    resp = api.create_booking(payload, gh)
    validate_error(resp, ApiErrorId.ERR_ROOM_KIND_MISMATCH.value)


# ---------------------------------------------------------------------------
# Corner: validations / corner_shuttle_full_rejected
# ---------------------------------------------------------------------------
def test_transport_segment_exceeding_shuttle_seats_rejected(api):
    """PRD §3.6: "the shuttle's `reserved_seats` plus the booking's `party_size` must not exceed the shuttle's `seat_capacity` (otherwise `ERR_SHUTTLE_FULL`, HTTP 409)."

    Design: Corner/validations/corner_shuttle_full_rejected
    """
    ctx = setup_booking_deposit_paid(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    shuttle = new_shuttle(api, ctx["retreat"]["id"], seat_capacity=1)
    resp = api.create_transport_segment(
        {"booking_id": ctx["booking"]["id"], "shuttle_id": shuttle["id"]}, ctx["guest_headers"])
    validate_error(resp, ApiErrorId.ERR_SHUTTLE_FULL.value)
