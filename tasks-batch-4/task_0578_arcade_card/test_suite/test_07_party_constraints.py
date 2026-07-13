"""Party booking gates: room time conflict (half-open, adjacency), venue aggregate
occupancy, room-availability at check-in, validation precedence, capacity, temporal
window, OCC on the booking version, and body well-formedness."""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers.fixtures import (
    set_clock, create_room, create_package, create_member, create_booking,
    confirm_booking, check_in_booking, get_booking, issue_extra_wristband,
    setup_confirmed_booking,
)

MANAGER = TEST_USERS["manager_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
CASHIER = TEST_USERS["cashier_headers"]


# --- Difficulty: room_pairwise_halfopen_overlap ---
def test_adjacent_room_booking_confirms(api):
    """PRD §3.5: "two windows that merely touch at the boundary, where one ends exactly as
    the other begins, do not overlap and are allowed."

    Design: Difficulty/resource_temporal_overlap/room_pairwise_halfopen_overlap
    """
    room = create_room(api, capacity=30, hourly_rate_cents=8_000)
    package = create_package(api, included_guests=10, included_chip_cents=0, combo_value_cents=0)
    host = create_member(api)
    a = create_booking(api, room["id"], package["id"], host["id"],
                       "2026-05-01T14:00:00Z", "2026-05-01T16:00:00Z", 5)
    confirm_booking(api, a["id"])
    b = create_booking(api, room["id"], package["id"], host["id"],
                       "2026-05-01T16:00:00Z", "2026-05-01T18:00:00Z", 5)
    confirmed_b = validate_success(api.confirm_party_booking(b["id"], COORDINATOR))
    assert confirmed_b["status"] == "CONFIRMED"


def test_overlapping_room_booking_rejected(api):
    """PRD §3.5: "the booking's half-open window from `start_at` up to but not including
    `end_at` must not overlap the window of any other non-`CANCELLED` booking on the same room
    ... An overlap is rejected with `ERR_ROOM_TIME_CONFLICT` (409)."

    Design: Difficulty/resource_temporal_overlap/room_pairwise_halfopen_overlap
    """
    room = create_room(api, capacity=30, hourly_rate_cents=8_000)
    package = create_package(api, included_guests=10, included_chip_cents=0, combo_value_cents=0)
    host = create_member(api)
    a = create_booking(api, room["id"], package["id"], host["id"],
                       "2026-05-01T14:00:00Z", "2026-05-01T16:00:00Z", 5)
    confirm_booking(api, a["id"])
    c = create_booking(api, room["id"], package["id"], host["id"],
                       "2026-05-01T15:00:00Z", "2026-05-01T17:00:00Z", 5)
    resp = api.confirm_party_booking(c["id"], COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_ROOM_TIME_CONFLICT, 409)
    assert validate_success(api.get_party_booking(c["id"], COORDINATOR))["status"] == "DRAFT"


# --- Difficulty: venue_aggregate_capacity_overlap ---
def test_aggregate_venue_capacity_exceeded_rejected(api):
    """PRD §3.5: "summing the `guest_count` of every `CONFIRMED` or `CHECKED_IN` booking whose
    window overlaps this window, plus this booking's own `guest_count`, must not exceed the
    maximum venue occupancy of 200 guests, else `ERR_VENUE_CAPACITY_EXCEEDED` (409)."

    Design: Difficulty/resource_temporal_overlap/venue_aggregate_capacity_overlap
    """
    room1 = create_room(api, capacity=200, hourly_rate_cents=8_000, name="Room I1")
    room2 = create_room(api, capacity=200, hourly_rate_cents=8_000, name="Room I2")
    package = create_package(api, included_guests=200, included_chip_cents=0, combo_value_cents=0)
    host = create_member(api)
    a = create_booking(api, room1["id"], package["id"], host["id"],
                       "2026-05-01T14:00:00Z", "2026-05-01T16:00:00Z", 150)
    confirm_booking(api, a["id"])
    b = create_booking(api, room2["id"], package["id"], host["id"],
                       "2026-05-01T15:00:00Z", "2026-05-01T17:00:00Z", 60)  # 150+60=210 > 200
    resp = api.confirm_party_booking(b["id"], COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_VENUE_CAPACITY_EXCEEDED, 409)
    assert validate_success(api.get_party_booking(b["id"], COORDINATOR))["status"] == "DRAFT"


def test_aggregate_venue_capacity_at_exact_cap_confirms(api):
    """PRD §3.5: "summing the `guest_count` of every `CONFIRMED` or `CHECKED_IN` booking whose
    window overlaps this window, plus this booking's own `guest_count`, must not exceed the
    maximum venue occupancy of 200 guests, else `ERR_VENUE_CAPACITY_EXCEEDED` (409)."

    Design: Difficulty/resource_temporal_overlap/venue_aggregate_capacity_overlap
    """
    room1 = create_room(api, capacity=200, hourly_rate_cents=8_000, name="Room I1")
    room2 = create_room(api, capacity=200, hourly_rate_cents=8_000, name="Room I2")
    package = create_package(api, included_guests=200, included_chip_cents=0, combo_value_cents=0)
    host = create_member(api)
    a = create_booking(api, room1["id"], package["id"], host["id"],
                       "2026-05-01T14:00:00Z", "2026-05-01T16:00:00Z", 150)
    confirm_booking(api, a["id"])
    b = create_booking(api, room2["id"], package["id"], host["id"],
                       "2026-05-01T15:00:00Z", "2026-05-01T17:00:00Z", 50)  # 150+50=200 == cap
    confirmed_b = validate_success(api.confirm_party_booking(b["id"], COORDINATOR))
    assert confirmed_b["status"] == "CONFIRMED"


# --- Difficulty: room_conflict_beats_guest_cap (priority pair) ---
def test_room_conflict_takes_precedence_over_guest_cap(api):
    """PRD §2.10: "**Temporal** — check-in must fall inside the booking window and
    confirmation must not clash with another room booking (§3.6, §3.5); violations are
    `ERR_OUTSIDE_BOOKING_WINDOW` and `ERR_ROOM_TIME_CONFLICT` (both 409)."
    PRD §2.10: "**Capacity constraints** — guest count within room capacity
    (`ERR_GUEST_COUNT_EXCEEDS_ROOM`), aggregate venue occupancy within the venue cap
    (`ERR_VENUE_CAPACITY_EXCEEDED`), and redemption quantity within available prize units
    (`ERR_INSUFFICIENT_STOCK`); all 409."

    Design: Difficulty/priority_pair_validation_conflict/room_conflict_beats_guest_cap
    """
    room = create_room(api, capacity=20, hourly_rate_cents=8_000)
    package = create_package(api, included_guests=10, included_chip_cents=0, combo_value_cents=0)
    host = create_member(api)
    a = create_booking(api, room["id"], package["id"], host["id"],
                       "2026-05-01T14:00:00Z", "2026-05-01T16:00:00Z", 10)
    confirm_booking(api, a["id"])
    b = create_booking(api, room["id"], package["id"], host["id"],
                       "2026-05-01T15:00:00Z", "2026-05-01T17:00:00Z", 25)  # overlaps AND 25>20
    resp = api.confirm_party_booking(b["id"], COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_ROOM_TIME_CONFLICT, 409)


def test_room_conflict_precedence_leaves_booking_draft(api):
    """PRD §3.5: "An overlap is rejected with `ERR_ROOM_TIME_CONFLICT` (409)."
    PRD §2.10: "This ordering is authoritative".

    Design: Difficulty/priority_pair_validation_conflict/room_conflict_beats_guest_cap
    """
    room = create_room(api, capacity=20, hourly_rate_cents=8_000)
    package = create_package(api, included_guests=10, included_chip_cents=0, combo_value_cents=0)
    host = create_member(api)
    a = create_booking(api, room["id"], package["id"], host["id"],
                       "2026-05-01T14:00:00Z", "2026-05-01T16:00:00Z", 10)
    confirm_booking(api, a["id"])
    b = create_booking(api, room["id"], package["id"], host["id"],
                       "2026-05-01T15:00:00Z", "2026-05-01T17:00:00Z", 25)
    api.confirm_party_booking(b["id"], COORDINATOR)
    assert validate_success(api.get_party_booking(b["id"], COORDINATOR))["status"] == "DRAFT"


# --- Difficulty: checkin_requires_room_available (cross-entity state dependency) ---
def test_checkin_blocked_while_room_in_maintenance(api):
    """PRD §3.6: "The room must be `AVAILABLE` and not in `MAINTENANCE`, else
    `ERR_ROOM_UNAVAILABLE` (409)".

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_room_available
    """
    ctx = setup_confirmed_booking(api, guest_count=2, included_chip_cents=1_000)
    bid = ctx["booking"]["id"]
    set_clock(api, "2026-05-01T14:30:00Z")
    validate_success(api.update_room(ctx["room"]["id"], {"status": "MAINTENANCE"}, MANAGER))
    resp = api.check_in_party_booking(bid, CASHIER)
    validate_error(resp, ApiErrorId.ERR_ROOM_UNAVAILABLE, 409)


def test_checkin_succeeds_after_room_restored(api):
    """PRD §3.6: "On check-in the booking's `checked_in_at` is set to the current clock
    instant, every wristband of the booking moves `ISSUED → ACTIVE`, and the booking's
    `version` increments."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_room_available
    """
    ctx = setup_confirmed_booking(api, guest_count=2, included_chip_cents=1_000)
    bid = ctx["booking"]["id"]
    set_clock(api, "2026-05-01T14:30:00Z")
    validate_success(api.update_room(ctx["room"]["id"], {"status": "MAINTENANCE"}, MANAGER))
    api.check_in_party_booking(bid, CASHIER)  # rejected
    validate_success(api.update_room(ctx["room"]["id"], {"status": "AVAILABLE"}, MANAGER))
    checked_in = validate_success(api.check_in_party_booking(bid, CASHIER))
    assert checked_in["status"] == "CHECKED_IN"


# --- Corner: confirm_guest_over_room_capacity ---
def test_confirm_guest_count_over_room_capacity_rejected(api):
    """PRD §3.5: "the `guest_count` must not exceed the room's `capacity`, else
    `ERR_GUEST_COUNT_EXCEEDS_ROOM` (409)."

    Design: Corner/validations/confirm_guest_over_room_capacity
    """
    room = create_room(api, capacity=5, hourly_rate_cents=8_000)
    package = create_package(api, included_guests=10, included_chip_cents=0, combo_value_cents=0)
    host = create_member(api)
    booking = create_booking(api, room["id"], package["id"], host["id"],
                             "2026-05-01T14:00:00Z", "2026-05-01T16:00:00Z", 8)
    resp = api.confirm_party_booking(booking["id"], COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_GUEST_COUNT_EXCEEDS_ROOM, 409)


# --- Corner: outside_window_checkin_rejected ---
def test_checkin_before_window_rejected(api):
    """PRD §3.6: "the logical clock must fall within the booking window — at or after
    `start_at` and strictly before `end_at` — else `ERR_OUTSIDE_BOOKING_WINDOW` (409)."

    Design: Corner/state_machines/outside_window_checkin_rejected
    """
    ctx = setup_confirmed_booking(api, guest_count=2, included_chip_cents=0)
    bid = ctx["booking"]["id"]
    set_clock(api, "2026-05-01T13:00:00Z")  # before 14:00 start
    resp = api.check_in_party_booking(bid, CASHIER)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_BOOKING_WINDOW, 409)
    assert validate_success(api.get_party_booking(bid, COORDINATOR))["status"] == "CONFIRMED"


# --- Corner: booking_end_before_start_rejected ---
def test_booking_end_before_start_rejected(api):
    """PRD §2.10: "for bookings, `end_at` must be strictly after `start_at`. A violation is
    `ERR_VALIDATION` (422)."

    Design: Corner/validations/booking_end_before_start_rejected
    """
    room = create_room(api, capacity=20, hourly_rate_cents=8_000)
    package = create_package(api, included_chip_cents=0, combo_value_cents=0)
    host = create_member(api)
    payload = {
        "room_id": room["id"], "package_id": package["id"], "host_member_id": host["id"],
        "start_at": "2026-05-01T16:00:00Z", "end_at": "2026-05-01T14:00:00Z", "guest_count": 2,
    }
    resp = api.create_party_booking(payload, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, 422)


# --- Corner: occ_wristband_issue_stale_booking_version ---
def test_extra_wristband_with_stale_booking_version_rejected(api):
    """PRD §2.8: "If another writer has already added a wristband — consuming room and venue
    headroom and advancing the booking's `version` — the issue is rejected with
    `ERR_STALE_VERSION` (HTTP 412), because the client's view of remaining headcount is stale."

    Design: Corner/cross_cutting_complexity_layers/occ_wristband_issue_stale_booking_version
    """
    ctx = setup_confirmed_booking(api, guest_count=2, included_chip_cents=0)
    bid = ctx["booking"]["id"]
    bv0 = ctx["booking"]["version"]
    issue_extra_wristband(api, bid, bv0)  # succeeds, bumps version
    resp = api.issue_wristband(bid, {"expected_booking_version": bv0}, CASHIER)  # stale
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
