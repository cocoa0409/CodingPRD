"""Room overlap (half-open / adjacency), optimistic concurrency on room and
reservation versions, and extension conflict / validation.

Covers difficulty queue rule resource_temporal_overlap and the corner
cross_cutting_complexity_layers / errors sections.
"""
from test_helpers import (
    validate_error, validate_success, ApiErrorId,
    setup_base, create_held_reservation, create_checked_in_reservation,
    get_room_version, get_reservation_version, set_clock,
    apply_extension, get_room,
    create_reservation_payload, create_extension_payload,
    make_customer_headers, make_front_desk_headers,
)

FD = make_front_desk_headers()


def _cust(c):
    return make_customer_headers(c["id"])


def test_reservation_overlap_rejected(api):
    """PRD §3.3: "The requested interval `[slot_start_utc, slot_end_utc)` must not
    overlap any active reservation on the same room, where "active" means a reservation
    in `HELD`, `CONFIRMED`, or `CHECKED_IN`; intervals are half-open, so two bookings
    that merely touch (one ending exactly when the next begins) do not overlap and are
    both allowed, while any genuine overlap is rejected with `ERR_ROOM_DOUBLE_BOOKED`."

    Existing HELD 20:00-22:00; a second create 21:30-23:00 genuinely overlaps ->
    ERR_ROOM_DOUBLE_BOOKED.

    Design: Difficulty/resource_temporal_overlap/reservation_overlap_rejected_adjacent_allowed
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-20T10:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    create_held_reservation(venue, room, customer,
                            "2026-07-20T20:00:00.000Z", "2026-07-20T22:00:00.000Z",
                            party_size=6)
    room_v = get_room_version(room["id"])
    payload = create_reservation_payload(
        venue["id"], room["id"], customer["id"], room_v,
        "2026-07-20T21:30:00.000Z", "2026-07-20T23:00:00.000Z", party_size=6,
    )
    validate_error(api.create_reservation(payload, _cust(customer)),
                   ApiErrorId.ERR_ROOM_DOUBLE_BOOKED.value)


def test_reservation_adjacent_booking_allowed(api):
    """PRD §3.3: "intervals are half-open, so two bookings that merely touch (one ending
    exactly when the next begins) do not overlap and are both allowed".

    Existing HELD 20:00-22:00; a second create starting exactly at 22:00 is allowed (201).

    Design: Difficulty/resource_temporal_overlap/reservation_overlap_rejected_adjacent_allowed
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-20T10:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    create_held_reservation(venue, room, customer,
                            "2026-07-20T20:00:00.000Z", "2026-07-20T22:00:00.000Z",
                            party_size=6)
    room_v = get_room_version(room["id"])
    payload = create_reservation_payload(
        venue["id"], room["id"], customer["id"], room_v,
        "2026-07-20T22:00:00.000Z", "2026-07-20T23:00:00.000Z", party_size=6,
    )
    data = validate_success(api.create_reservation(payload, _cust(customer)), 201)
    assert data["status"] == "HELD"


def test_extension_overlap_into_later_booking_rejected(api):
    """PRD §3.5: "the server re-runs overlap detection on the room over just the newly
    claimed window — the half-open interval from the old end up to the new end — and if
    that window collides with a later active reservation on the same room (adjacency,
    where one ends exactly as the other begins, remaining allowed), the extension is
    rejected with `ERR_EXTENSION_CONFLICT`."

    R1 20:00-22:00, R2 22:30-23:30 on the same room. Extending R1 to 23:00 claims
    [22:00,23:00) which overlaps R2 -> ERR_EXTENSION_CONFLICT.

    Design: Difficulty/resource_temporal_overlap/extension_overlap_into_later_booking_rejected
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-21T10:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res1 = create_held_reservation(venue, room, customer,
                                   "2026-07-21T20:00:00.000Z", "2026-07-21T22:00:00.000Z",
                                   party_size=6)
    create_held_reservation(venue, room, customer,
                            "2026-07-21T22:30:00.000Z", "2026-07-21T23:30:00.000Z",
                            party_size=6)
    res1_v = get_reservation_version(res1["id"], customer)
    payload = create_extension_payload("2026-07-21T23:00:00.000Z", res1_v)
    validate_error(api.create_extension(res1["id"], payload, _cust(customer)),
                   ApiErrorId.ERR_EXTENSION_CONFLICT.value)


def test_occ_reservation_create_stale_room_version(api):
    """PRD §2.7: "If that value does not match the room's current `version` — because,
    since the client read it, a booking was created against the room, the room was taken
    out of service, or it was otherwise mutated — the create is rejected with
    `ERR_STALE_ROOM_VERSION` (HTTP 412)."

    A first booking advances Room.version; a second create still carrying the pre-bump
    version -> ERR_STALE_ROOM_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_reservation_create_stale_room_version
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-22T10:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    room_v0 = get_room_version(room["id"])
    create_held_reservation(venue, room, customer,
                            "2026-08-22T18:00:00.000Z", "2026-08-22T19:00:00.000Z",
                            party_size=4, room_version=room_v0)
    payload = create_reservation_payload(
        venue["id"], room["id"], customer["id"], room_v0,
        "2026-08-22T20:00:00.000Z", "2026-08-22T21:00:00.000Z", party_size=4,
    )
    validate_error(api.create_reservation(payload, _cust(customer)),
                   ApiErrorId.ERR_STALE_ROOM_VERSION.value)


def test_occ_extension_stale_reservation_version(api):
    """PRD §2.7: "An extension-create request must therefore carry
    `expected_reservation_version` ... If that value does not match the reservation's
    current `version`, the extension is rejected with `ERR_STALE_RESERVATION_VERSION`
    (HTTP 412), and no `Extension` row is written."

    A first extension advances Reservation.version; a second extension carrying the
    pre-bump version -> ERR_STALE_RESERVATION_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_extension_stale_reservation_version
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-23T10:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_held_reservation(venue, room, customer,
                                  "2026-08-23T20:00:00.000Z", "2026-08-23T21:00:00.000Z",
                                  party_size=4)
    res_v0 = res["version"]
    apply_extension(res, customer, "2026-08-23T21:30:00.000Z", res_v0)
    payload = create_extension_payload("2026-08-23T22:00:00.000Z", res_v0)
    validate_error(api.create_extension(res["id"], payload, _cust(customer)),
                   ApiErrorId.ERR_STALE_RESERVATION_VERSION.value)


def test_room_version_increments_on_occupy(api):
    """PRD §3.4: "drives the room from `AVAILABLE → OCCUPIED` (incrementing the room's
    `version` by 1)".
    PRD §2.4: "The `version` field is an integer that starts at 1 when the resource is
    created and increases by exactly 1 on each mutation".

    After check-in the room is OCCUPIED and its version has advanced past the create
    value of 1.

    Design: Corner/cross_cutting_complexity_layers/room_version_increments_on_occupy
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-24T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    create_checked_in_reservation(venue, room, customer,
                                  "2026-08-24T20:00:00.000Z", "2026-08-24T22:00:00.000Z",
                                  checkin_clock_utc="2026-08-24T20:00:00.000Z")
    after = get_room(room["id"])
    assert after["status"] == "OCCUPIED"
    assert after["version"] > 1


def test_extension_new_end_not_after_current_rejected(api):
    """PRD §3.5: "The extension payload supplies the proposed `new_slot_end_utc`, which
    must be strictly after the reservation's current `slot_end_utc`".
    PRD §2.8: "required fields must be present, enums must be valid, `slot_end_utc` must
    be strictly after `slot_start_utc`, and numeric fields must lie within their declared
    ranges, failing which the request is rejected with `ERR_INVALID_REQUEST`."

    Extension proposing an earlier end (21:00 vs current 22:00) -> ERR_INVALID_REQUEST.

    Design: Corner/errors/extension_new_end_not_after_current_end_rejected
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-19T10:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_held_reservation(venue, room, customer,
                                  "2026-08-19T20:00:00.000Z", "2026-08-19T22:00:00.000Z",
                                  party_size=4)
    payload = create_extension_payload("2026-08-19T21:00:00.000Z", res["version"])
    validate_error(api.create_extension(res["id"], payload, _cust(customer)),
                   ApiErrorId.ERR_INVALID_REQUEST.value)
