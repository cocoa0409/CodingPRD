"""Resource temporal overlap: amenity buffer-expanded pairwise overlap vs
property-level guest concurrency capacity.

Queue A (Difficulty):
resource_temporal_overlap/booking_buffer_overlap_on_amenity,
resource_temporal_overlap/guest_concurrency_capacity_on_property.
"""
from test_helpers import (
    fixtures as fx,
    make_resident_headers,
    validate_error,
    validate_paginated,
    ApiErrorId,
)


def _setup_buffered_amenity_with_booking(api):
    """GYM capacity 1, buffer 30 min; booking A 10:00-11:00 CONFIRMED. Returns
    (amenity_id, resident_id, next_version)."""
    base = fx.setup_amenity_booking_base(
        api, clock="2026-05-20T00:00:00Z",
        resident_overrides={"full_name": "Nia", "email": "nia@x.com"},
        amenity_overrides={
            "name": "Gym", "amenity_type": "GYM", "capacity": 1,
            "base_rate_cents_per_hour": 4000, "deposit_cents": 0,
            "buffer_minutes": 30, "open_minute": 0, "close_minute": 1440,
        },
    )
    fx.new_booking(api, base["amenity"]["id"], base["resident"]["id"],
                   "2026-06-05T10:00:00Z", "2026-06-05T11:00:00Z",
                   expected_version=base["amenity"]["version"])
    version = fx.current_amenity_version(api, base["amenity"]["id"])
    return base["amenity"]["id"], base["resident"]["id"], version


def test_booking_within_buffer_gap_rejected(api):
    """PRD §3.2: "For overlap testing, each occupied interval is expanded by the
    amenity's `buffer_minutes` so that consecutive bookings must leave at least
    that gap; occupancy at any instant counts bookings in `CONFIRMED` or
    `CHECKED_IN` status whose half-open window covers that instant, and this
    count including the new booking must not exceed `capacity`."

    A booking starting 15 min after another ends collides once each interval is
    expanded by the 30-min buffer, so it is rejected with ERR_BOOKING_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/booking_buffer_overlap_on_amenity
    """
    amenity_id, resident_id, version = _setup_buffered_amenity_with_booking(api)
    resp = api.create_booking(
        {"amenity_id": amenity_id, "resident_id": resident_id,
         "start_at": "2026-06-05T11:15:00Z", "end_at": "2026-06-05T12:00:00Z",
         "expected_amenity_version": version},
        make_resident_headers(resident_id),
    )
    validate_error(resp, ApiErrorId.ERR_BOOKING_OVERLAP.value)


def test_buffer_conflict_leaves_only_first_booking(api):
    """PRD §3.2: "an occupancy conflict with `ERR_BOOKING_OVERLAP`."

    The rejected second booking creates nothing: only booking A remains on the
    amenity.

    Design: Difficulty/resource_temporal_overlap/booking_buffer_overlap_on_amenity
    """
    amenity_id, resident_id, version = _setup_buffered_amenity_with_booking(api)
    api.create_booking(
        {"amenity_id": amenity_id, "resident_id": resident_id,
         "start_at": "2026-06-05T11:15:00Z", "end_at": "2026-06-05T12:00:00Z",
         "expected_amenity_version": version},
        make_resident_headers(resident_id),
    )
    _, meta = validate_paginated(api.list_bookings(fx.PM, params={"amenity_id": amenity_id}))
    assert meta["total_count"] == 1, "only booking A exists"


def _setup_property_with_one_guest_pass(api):
    """Property guest_parking_capacity 1, guest_window_hours 48; pass 1 issued
    for 10:00-14:00. Returns (resident_id,)."""
    prop = fx.new_property(api, name="Elm", address="8 Elm St",
                           guest_parking_capacity=1, guest_window_hours=48)
    unit = fx.new_unit(api, prop["id"], unit_number="802")
    resident = fx.new_resident(api, unit["id"], full_name="Omar", email="omar@x.com")
    fx.set_clock(api, "2026-05-20T00:00:00Z")
    fx.get_success_data(api.create_guest_pass(
        {"resident_id": resident["id"], "guest_name": "Guest1",
         "arrival_at": "2026-06-01T10:00:00Z", "expected_departure_at": "2026-06-01T14:00:00Z"},
        make_resident_headers(resident["id"]),
    ))
    return resident["id"]


def test_overlapping_guest_pass_exceeds_capacity(api):
    """PRD §3.6: "that admitting this pass keeps the number of concurrently
    active guest passes over the pass's window within the property's
    `guest_parking_capacity` (otherwise `ERR_GUEST_CAPACITY_EXCEEDED`)."

    On a property whose guest_parking_capacity is 1, a second pass whose window
    overlaps the first pushes concurrency to 2 and is rejected with
    ERR_GUEST_CAPACITY_EXCEEDED.

    Design: Difficulty/resource_temporal_overlap/guest_concurrency_capacity_on_property
    """
    resident_id = _setup_property_with_one_guest_pass(api)
    resp = api.create_guest_pass(
        {"resident_id": resident_id, "guest_name": "Guest2",
         "arrival_at": "2026-06-01T12:00:00Z", "expected_departure_at": "2026-06-01T16:00:00Z"},
        make_resident_headers(resident_id),
    )
    validate_error(resp, ApiErrorId.ERR_GUEST_CAPACITY_EXCEEDED.value)


def test_rejected_guest_pass_not_created(api):
    """PRD §3.6: "Concurrency counts passes that are active — `ISSUED` or
    `CHECKED_IN` — whose windows overlap."

    The over-capacity second pass is not created; only the first ISSUED pass
    remains for the resident.

    Design: Difficulty/resource_temporal_overlap/guest_concurrency_capacity_on_property
    """
    resident_id = _setup_property_with_one_guest_pass(api)
    api.create_guest_pass(
        {"resident_id": resident_id, "guest_name": "Guest2",
         "arrival_at": "2026-06-01T12:00:00Z", "expected_departure_at": "2026-06-01T16:00:00Z"},
        make_resident_headers(resident_id),
    )
    _, meta = validate_paginated(api.list_guest_passes(fx.PM, params={"resident_id": resident_id}))
    assert meta["total_count"] == 1, "only the first pass exists"
