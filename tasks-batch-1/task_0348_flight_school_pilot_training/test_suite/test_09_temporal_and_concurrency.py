"""Temporal-overlap and optimistic-concurrency claims: the half-open aircraft
schedule overlap rule (end exclusive) and the aircraft-version OCC guard on
booking creation.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    DISPATCHER,
    ApiErrorId,
    setup_active_enrollment, create_aircraft, create_booking, report_squawk,
    get_aircraft_version, get_booking,
    create_booking_payload,
)


def test_aircraft_overlapping_window_confirm_rejected(api):
    """PRD §3.3: "The requested window must not overlap, on a half-open
    `[start_at, end_at)` basis, any other booking on the same aircraft that is
    `REQUESTED`, `CONFIRMED`, or `DISPATCHED`; an overlap yields
    `ERR_AIRCRAFT_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/aircraft_half_open_overlap_conflict
    """
    base = setup_active_enrollment(deposit_cents=300000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000)
    bk_base = create_booking(
        base["enrollment"]["id"], aircraft["id"], "SOLO", 2.0,
        window=("2026-07-01T14:00:00.000Z", "2026-07-01T16:00:00.000Z"),
    )
    api.confirm_booking(bk_base["id"], DISPATCHER)
    # Overlapping window [15:00,17:00) on the SAME aircraft.
    bk_overlap = create_booking(
        base["enrollment"]["id"], aircraft["id"], "SOLO", 2.0,
        window=("2026-07-01T15:00:00.000Z", "2026-07-01T17:00:00.000Z"),
    )
    validate_error(api.confirm_booking(bk_overlap["id"], DISPATCHER),
                   ApiErrorId.ERR_AIRCRAFT_TIME_CONFLICT.value)
    assert get_booking(bk_overlap["id"])["status"] == "REQUESTED"


def test_aircraft_adjacent_window_confirm_succeeds_end_exclusive(api):
    """PRD §3.3: "The requested window must not overlap, on a half-open
    `[start_at, end_at)` basis, any other booking on the same aircraft that is
    `REQUESTED`, `CONFIRMED`, or `DISPATCHED`; an overlap yields
    `ERR_AIRCRAFT_TIME_CONFLICT`."
    PRD §3.3: "The reservation window is half-open: it covers `start_at` up to but
    not including `end_at`."

    Design: Difficulty/resource_temporal_overlap/aircraft_half_open_overlap_conflict
    """
    base = setup_active_enrollment(deposit_cents=300000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000)
    bk_base = create_booking(
        base["enrollment"]["id"], aircraft["id"], "SOLO", 2.0,
        window=("2026-07-01T14:00:00.000Z", "2026-07-01T16:00:00.000Z"),
    )
    api.confirm_booking(bk_base["id"], DISPATCHER)
    # Adjacent window [16:00,18:00): start equals the prior end, which is excluded.
    bk_adj = create_booking(
        base["enrollment"]["id"], aircraft["id"], "SOLO", 2.0,
        window=("2026-07-01T16:00:00.000Z", "2026-07-01T18:00:00.000Z"),
    )
    confirmed = validate_success(api.confirm_booking(bk_adj["id"], DISPATCHER))
    assert confirmed["status"] == "CONFIRMED"


def test_booking_create_with_stale_aircraft_version_rejected(api):
    """PRD §2.7: "If that value does not equal the aircraft's current `version`, the
    create is rejected with `ERR_STALE_AIRCRAFT_VERSION` (HTTP 412). Because any
    successful booking create advances the aircraft's `version` by one — as does an
    automatic grounding — a client whose view predates another writer's create or a
    grounding is, by definition, stale, and its create is refused..."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_aircraft_version_on_booking_create
    """
    base = setup_active_enrollment(deposit_cents=100000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000)
    stale_version = get_aircraft_version(aircraft["id"])
    # A grounding advances the aircraft version, making `stale_version` stale.
    report_squawk(aircraft["id"], True)
    payload = create_booking_payload(
        base["enrollment"]["id"], aircraft["id"], "DUAL",
        "2026-07-01T14:00:00.000Z", "2026-07-01T16:00:00.000Z", 2.0, stale_version,
        instructor_id=base["instructor"]["id"],
    )
    validate_error(api.create_booking(payload, DISPATCHER), ApiErrorId.ERR_STALE_AIRCRAFT_VERSION.value)


def test_booking_create_with_matching_aircraft_version_succeeds(api):
    """PRD §2.7: "A booking-create request must carry `expected_aircraft_version`, a
    non-optional field holding the `version` the client last observed when it read
    the target aircraft. If that value does not equal the aircraft's current
    `version`, the create is rejected with `ERR_STALE_AIRCRAFT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_matching_aircraft_version_on_booking_create_succeeds
    """
    base = setup_active_enrollment(deposit_cents=100000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000)
    version = get_aircraft_version(aircraft["id"])  # no intervening mutation
    payload = create_booking_payload(
        base["enrollment"]["id"], aircraft["id"], "DUAL",
        "2026-07-01T14:00:00.000Z", "2026-07-01T16:00:00.000Z", 2.0, version,
        instructor_id=base["instructor"]["id"],
    )
    data = validate_success(api.create_booking(payload, DISPATCHER), 201)
    assert data["status"] == "REQUESTED"
    assert data["estimated_cost_cents"] == 42000


def test_list_bookings_filtered_by_aircraft(api):
    """PRD §4: "List bookings (filter by enrollment, aircraft, instructor, or status)"
    PRD §2.5: "relationships are expressed through foreign-key body fields resolved
    by filtered list queries rather than by nested URLs."

    Design: Corner/endpoints/filtered_list_bookings_by_aircraft
    """
    base = setup_active_enrollment(deposit_cents=100000)
    aircraft = create_aircraft(rental_rate_cents_per_hour=15000)
    booking = create_booking(
        base["enrollment"]["id"], aircraft["id"], "DUAL", 2.0,
        instructor_id=base["instructor"]["id"],
    )
    data, _meta = validate_paginated(api.list_bookings(DISPATCHER, params={"aircraft_id": aircraft["id"]}))
    ids = [b["id"] for b in data]
    assert booking["id"] in ids
    for b in data:
        assert b["aircraft_id"] == aircraft["id"]
