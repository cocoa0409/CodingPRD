"""Resource shapes for the microtransit on-demand API.

Covers what a created row looks like on the way back out: verbatim echo of the
supplied inputs, the declared defaults for omitted optional inputs, the
system-seeded counters, single-row retrieval, list pagination metadata, the
append-only ledger row's reduced field set, and the intake rejections that guard
request shape and body-level referential integrity.
"""

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import ABSENT_UUID, CLOCK_STARTUP_UTC, SERVICE_DATE
from test_helpers.factories import service_zone_payload, vehicle_block_payload
from test_helpers.test_users import (
    DISPATCHER_HEADERS,
    FINANCE_ANALYST_HEADERS,
    ZONE_ADMIN_HEADERS,
    make_rider_headers,
)

SERVICE_DAY_OPEN_UTC = "2026-08-03T06:00:00Z"
SERVICE_DAY_PICKUP_UTC = "2026-08-03T07:00:00Z"
ABSENT_ZONE_UUID = "00000000-0000-4000-8000-000000000001"
ABSENT_RIDER_UUID = "00000000-0000-4000-8000-000000000002"


# ─── Required-input-only payload builders ──────────────────────────────────
# The shared factories always fill the optional inputs, so these local builders
# supply the required inputs and nothing else, which is what a defaults probe
# needs.


def _zone_required_only(name="Defaults Zone", zone_code="DEF") -> dict:
    return {
        "name": name,
        "zone_code": zone_code,
        "max_walk_meters": 600,
        "detour_tolerance_pct": 0.25,
        "detour_tolerance_floor_minutes": 6,
        "base_fare_cents": 250,
        "fare_cap_cents_daily": 600,
        "fare_cap_cents_weekly": 2500,
    }


def _create_zone_required_only(name="Defaults Zone", zone_code="DEF") -> dict:
    return validate_success(
        api_client.create_service_zone(
            _zone_required_only(name, zone_code), ZONE_ADMIN_HEADERS
        ),
        201,
    )


def _create_stop_required_only(zone_id, stop_code, corridor_index) -> dict:
    return validate_success(
        api_client.create_virtual_stop(
            {
                "zone_id": zone_id,
                "stop_code": stop_code,
                "corridor_index": corridor_index,
                "walk_shed_meters": 400,
            },
            ZONE_ADMIN_HEADERS,
        ),
        201,
    )


def _build_defaults_world() -> dict:
    """One row of every create-bearing resource, each built from its required
    inputs only, so every optional input falls back to its declared default."""
    fixtures.set_clock(SERVICE_DAY_OPEN_UTC)
    zone_at_create = _create_zone_required_only()
    zone = fixtures.activate_zone(zone_at_create["id"])
    zone_id = zone["id"]

    origin_at_create = _create_stop_required_only(zone_id, "S0", 0)
    origin = fixtures.approve_stop(origin_at_create["id"])
    destination_at_create = _create_stop_required_only(zone_id, "S4", 4)
    destination = fixtures.approve_stop(destination_at_create["id"])

    vehicle = validate_success(
        api_client.create_vehicle(
            {"zone_id": zone_id, "vehicle_code": "V1", "seat_capacity": 6},
            ZONE_ADMIN_HEADERS,
        ),
        201,
    )
    driver = validate_success(
        api_client.create_driver(
            {"zone_id": zone_id, "driver_code": "D1"}, ZONE_ADMIN_HEADERS
        ),
        201,
    )
    rider = validate_success(
        api_client.create_rider(
            {"zone_id": zone_id, "rider_code": "R1"}, ZONE_ADMIN_HEADERS
        ),
        201,
    )
    block = validate_success(
        api_client.create_vehicle_block(
            vehicle_block_payload(zone_id, vehicle["id"], driver["id"]),
            DISPATCHER_HEADERS,
        ),
        201,
    )
    trip = validate_success(
        api_client.create_trip_request(
            {
                "zone_id": zone_id,
                "rider_id": rider["id"],
                "origin_stop_id": origin["id"],
                "destination_stop_id": destination["id"],
                "requested_pickup_utc": SERVICE_DAY_PICKUP_UTC,
            },
            make_rider_headers(rider["id"]),
        ),
        201,
    )
    return {
        "zone_at_create": zone_at_create,
        "zone": zone,
        "origin_at_create": origin_at_create,
        "origin": origin,
        "destination_at_create": destination_at_create,
        "destination": destination,
        "vehicle": vehicle,
        "driver": driver,
        "rider": rider,
        "block": block,
        "trip": trip,
    }


def _build_three_blocks() -> dict:
    """One vehicle carrying three legally spaced blocks on the service day."""
    fixtures.set_clock("2026-08-03T05:00:00Z")
    zone = fixtures.create_active_zone()
    vehicle = fixtures.create_vehicle(zone["id"], "V1")
    driver_one = fixtures.create_driver(zone["id"], "D1")
    driver_two = fixtures.create_driver(zone["id"], "D2")
    driver_three = fixtures.create_driver(zone["id"], "D3")
    block_one = fixtures.create_block(
        zone["id"],
        vehicle["id"],
        driver_one["id"],
        start_utc="2026-08-03T06:00:00Z",
        end_utc="2026-08-03T08:00:00Z",
    )
    block_two = fixtures.create_block(
        zone["id"],
        vehicle["id"],
        driver_two["id"],
        start_utc="2026-08-03T08:00:00Z",
        end_utc="2026-08-03T10:00:00Z",
    )
    block_three = fixtures.create_block(
        zone["id"],
        vehicle["id"],
        driver_three["id"],
        block_type="SURGE",
        start_utc="2026-08-03T10:30:00Z",
        end_utc="2026-08-03T12:00:00Z",
    )
    return {
        "zone": zone,
        "blocks": [block_one, block_two, block_three],
    }


# ─── Creation echo ─────────────────────────────────────────────────────────


def test_service_zone_create_echoes_every_supplied_field():
    """A service-zone create answers 201 and reads every supplied field back verbatim.

    PRD: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    Design: Corner/entities/service_zone_creation_echoes_every_supplied_field
    """
    fixtures.set_clock(CLOCK_STARTUP_UTC)
    payload = service_zone_payload(
        name="Riverbend Microtransit",
        zone_code="RBM",
        max_walk_meters=600,
        detour_tolerance_pct=0.25,
        detour_tolerance_floor_minutes=6,
        base_fare_cents=250,
        fare_cap_cents_daily=600,
        fare_cap_cents_weekly=2500,
        on_time_window_minutes=10,
        curb_capacity_per_bucket=2,
    )

    response = api_client.create_service_zone(payload, ZONE_ADMIN_HEADERS)

    zone = validate_success(response, 201)
    assert response.json()["response_type"] == "object"
    assertions.assert_fields(
        zone,
        name="Riverbend Microtransit",
        zone_code="RBM",
        max_walk_meters=600,
        detour_tolerance_floor_minutes=6,
        base_fare_cents=250,
        fare_cap_cents_daily=600,
        fare_cap_cents_weekly=2500,
        on_time_window_minutes=10,
        curb_capacity_per_bucket=2,
        status="DRAFT",
    )
    assert zone["detour_tolerance_pct"] == pytest.approx(0.25, abs=0.01)
    assertions.assert_versioned_entity(zone)
    assert zone["version"] == 1

    stored = fixtures.refresh_zone(zone["id"])
    assertions.assert_fields(
        stored,
        id=zone["id"],
        name="Riverbend Microtransit",
        zone_code="RBM",
        max_walk_meters=600,
        detour_tolerance_floor_minutes=6,
        base_fare_cents=250,
        fare_cap_cents_daily=600,
        fare_cap_cents_weekly=2500,
        on_time_window_minutes=10,
        curb_capacity_per_bucket=2,
        status="DRAFT",
    )


# ─── Defaults for omitted optional inputs and system-seeded fields ─────────


def test_omitted_trip_optional_inputs_take_their_declared_defaults():
    """A trip intaken without its three optional inputs defaults to party size 1, no accessible handling and no connection.

    PRD: "Three optional inputs complete it: `party_size`, the number of ambulatory seats wanted, which defaults to 1 and must be at least 1 and at most 6; `wav_required`, a request that the trip be handled as wheelchair-accessible; and `connection_id`, naming the rail or bus departure this first or last-mile trip is timed to, which defaults to null."

    Design: Corner/entities/defaults_applied_for_omitted_optional_inputs_and_system_seeded_fields
    """
    world = _build_defaults_world()

    trip = world["trip"]
    assertions.assert_fields(
        trip,
        party_size=1,
        wav_required=False,
        connection_id=None,
    )
    assertions.assert_trip_state(trip, "RECEIVED", "UNPRICED")

    stored = fixtures.refresh_trip(trip["id"])
    assertions.assert_fields(
        stored,
        party_size=1,
        wav_required=False,
        connection_id=None,
    )


def test_omitted_stop_optional_inputs_take_their_declared_defaults():
    """A virtual stop placed without accessibility or a pairing defaults to UNKNOWN and null.

    PRD: "The curb-side path condition is recorded in `accessibility`, one of `ACCESSIBLE_PATH`, `STAIRS_ONLY` or `UNKNOWN`, defaulting to `UNKNOWN` when omitted."

    Design: Corner/entities/defaults_applied_for_omitted_optional_inputs_and_system_seeded_fields
    """
    world = _build_defaults_world()

    at_create = world["destination_at_create"]
    assertions.assert_fields(
        at_create,
        accessibility="UNKNOWN",
        paired_stop_id=None,
        walk_shed_meters=400,
        corridor_index=4,
        status="PROPOSED",
    )

    stored = fixtures.refresh_stop(at_create["id"])
    assertions.assert_fields(
        stored,
        accessibility="UNKNOWN",
        paired_stop_id=None,
    )


def test_omitted_roster_and_policy_optional_inputs_take_their_declared_defaults():
    """Omitted securement positions, certification, fare category, mobility device and the two zone tolerances all fall back to their declared defaults.

    PRD: "A `ZoneAdmin` adds a **vehicle** to a zone with a `vehicle_code` unique within that `zone_id`, a `seat_capacity` of at least 1 and at most 24 ambulatory seats available for pooling, and a `wav_positions` count of wheelchair securement positions between 0 and 4 inclusive, defaulting to 0."

    Design: Corner/entities/defaults_applied_for_omitted_optional_inputs_and_system_seeded_fields
    """
    world = _build_defaults_world()

    assertions.assert_fields(
        world["vehicle"],
        wav_positions=0,
        is_wav=False,
        seat_capacity=6,
        status="AVAILABLE",
    )
    assertions.assert_fields(world["driver"], wav_certified=False, status="ACTIVE")
    assertions.assert_fields(
        world["rider"], fare_category="FULL", mobility_device="NONE"
    )
    assertions.assert_fields(
        world["zone_at_create"],
        on_time_window_minutes=5,
        curb_capacity_per_bucket=2,
    )


def test_system_seeded_fields_start_at_their_declared_values():
    """Every server-seeded counter on a fresh zone, driver, rider, block and trip starts at its declared value rather than null.

    PRD: "A scheduled block is created in `SCHEDULED` with `version` 1, with `seats_committed`, `wav_positions_committed` and `boardings_count` all at 0, with `committed_index_min` and `committed_index_max` both null, with `opened_at` and `closed_at` both null, with `actual_revenue_hours` at 0.00, and with `scheduled_revenue_hours` derived from the window: the difference between `end_utc` and `start_utc` expressed in hours, to 2 decimal places, rounded half up."

    Design: Corner/entities/defaults_applied_for_omitted_optional_inputs_and_system_seeded_fields
    """
    world = _build_defaults_world()

    block = world["block"]
    assertions.assert_block_state(block, "SCHEDULED")
    assertions.assert_block_commitments(
        block,
        seats_committed=0,
        wav_positions_committed=0,
        committed_index_min=None,
        committed_index_max=None,
    )
    assertions.assert_fields(block, boardings_count=0, opened_at=None, closed_at=None)
    assert block["actual_revenue_hours"] == pytest.approx(0.00, abs=0.01)
    assert block["scheduled_revenue_hours"] == pytest.approx(4.00, abs=0.01)
    assert block["version"] == 1

    zone = world["zone_at_create"]
    assertions.assert_fields(
        zone,
        status="DRAFT",
        completed_trip_count=0,
        unserved_trip_count=0,
        equivalence_verdict="COMPLIANT",
    )
    for field in (
        "avg_wait_minutes",
        "avg_ride_minutes",
        "boardings_per_revenue_hour",
        "wav_avg_wait_minutes",
        "nonwav_avg_wait_minutes",
    ):
        assert zone[field] == pytest.approx(0.00, abs=0.01), field
    assert zone["wav_equivalence_ratio"] == pytest.approx(0.000, abs=0.01)

    assertions.assert_fields(world["driver"], consecutive_decline_count=0)
    assertions.assert_fields(
        world["rider"],
        fare_counter_date=None,
        fare_counter_week_start=None,
        daily_fare_paid_cents=0,
        weekly_fare_paid_cents=0,
    )

    trip = world["trip"]
    assertions.assert_fields(trip, match_attempt_count=0)
    assertions.assert_null_fields(
        trip,
        "assigned_block_id",
        "projected_detour_minutes",
        "promised_pickup_utc",
        "promised_dropoff_utc",
        "quoted_fare_cents",
        "charged_fare_cents",
        "applied_cap",
        "no_service_reason",
        "actual_pickup_utc",
        "actual_dropoff_utc",
        "wait_minutes",
        "ride_minutes",
    )


# ─── Retrieval ─────────────────────────────────────────────────────────────


def test_virtual_stop_retrieval_returns_the_stored_row():
    """Reading one virtual stop returns exactly the row that was placed, still PROPOSED.

    PRD: "A stop names its zone through `zone_id` and carries an operator-assigned `stop_code` that must be unique within that zone, an integer `corridor_index` between 0 and 500 inclusive giving its position on the corridor, and a `walk_shed_meters` value of zero or more stating the farthest walking distance the stop is advertised to serve."

    Design: Corner/entities/virtual_stop_retrieval_returns_the_stored_row
    """
    fixtures.set_clock(CLOCK_STARTUP_UTC)
    zone = fixtures.create_active_zone()
    created = fixtures.create_stop(
        zone["id"], "S7", 7, walk_shed_meters=350, accessibility="STAIRS_ONLY"
    )

    response = api_client.get_virtual_stop(created["id"], DISPATCHER_HEADERS)

    stop = validate_success(response, 200)
    assert response.json()["response_type"] == "object"
    assertions.assert_fields(
        stop,
        id=created["id"],
        zone_id=zone["id"],
        stop_code="S7",
        corridor_index=7,
        walk_shed_meters=350,
        accessibility="STAIRS_ONLY",
        paired_stop_id=None,
        status="PROPOSED",
    )
    assertions.assert_versioned_entity(stop)
    assert stop["version"] == 1


# ─── Listing ───────────────────────────────────────────────────────────────


def test_vehicle_block_listing_reports_total_count_and_has_more():
    """Paging three stored blocks two at a time reports the pre-pagination total and flips has_more on the last page.

    PRD: "The `meta` object of a list response carries `limit` (the effective page size), `offset` (the effective starting position), `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when rows remain beyond the current page)."

    Design: Corner/entities/vehicle_block_listing_reports_total_count_and_has_more
    """
    world = _build_three_blocks()
    zone_id = world["zone"]["id"]
    all_ids = {block["id"] for block in world["blocks"]}

    first = api_client.list_vehicle_blocks(
        DISPATCHER_HEADERS, params={"zone_id": zone_id, "limit": 2, "offset": 0}
    )
    first_rows, first_meta = validate_paginated(first)
    assert first.json()["response_type"] == "array"
    assertions.assert_row_count(first_rows, 2)
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second = api_client.list_vehicle_blocks(
        DISPATCHER_HEADERS, params={"zone_id": zone_id, "limit": 2, "offset": 2}
    )
    second_rows, second_meta = validate_paginated(second)
    assertions.assert_row_count(second_rows, 1)
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    paged_ids = assertions.ids_of(first_rows) + assertions.ids_of(second_rows)
    assert len(set(paged_ids)) == 3, f"a row was paged twice: {paged_ids}"
    assert set(paged_ids) == all_ids


def test_vehicle_block_listing_filters_on_block_type():
    """Filtering the block listing on block_type narrows total_count to the matching rows only.

    PRD: "Vehicle blocks filter on `zone_id`, `vehicle_id`, `driver_id`, `state` and `block_type`."

    Design: Corner/entities/vehicle_block_listing_reports_total_count_and_has_more
    """
    world = _build_three_blocks()
    zone_id = world["zone"]["id"]
    surge_block = world["blocks"][2]

    response = api_client.list_vehicle_blocks(
        DISPATCHER_HEADERS, params={"zone_id": zone_id, "block_type": "SURGE"}
    )

    rows, meta = validate_paginated(response)
    assertions.assert_row_count(rows, 1)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert rows[0]["id"] == surge_block["id"]
    assert rows[0]["block_type"] == "SURGE"


# ─── Not found ─────────────────────────────────────────────────────────────


def test_trip_request_get_with_unknown_id_returns_not_found():
    """Reading a trip request that never existed answers 404 with the trip-request not-found code.

    PRD: "The twelve not-found codes are `ERR_SERVICE_ZONE_NOT_FOUND`, `ERR_VIRTUAL_STOP_NOT_FOUND`, `ERR_TRANSIT_CONNECTION_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_RIDER_NOT_FOUND`, `ERR_DEMAND_FORECAST_NOT_FOUND`, `ERR_VEHICLE_BLOCK_NOT_FOUND`, `ERR_TRIP_REQUEST_NOT_FOUND`, `ERR_POOL_ASSIGNMENT_NOT_FOUND`, `ERR_FARE_TRANSACTION_NOT_FOUND` and `ERR_SUBSIDY_REPORT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/entities/trip_request_get_with_unknown_id_returns_not_found
    """
    fixtures.set_clock(CLOCK_STARTUP_UTC)

    response = api_client.get_trip_request(ABSENT_UUID, DISPATCHER_HEADERS)

    validate_error(response, ApiErrorId.ERR_TRIP_REQUEST_NOT_FOUND.value, 404)

    listing = api_client.list_trip_requests(DISPATCHER_HEADERS)
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0
    assertions.assert_row_count(rows, 0)


# ─── Required fields ───────────────────────────────────────────────────────


def test_vehicle_create_missing_seat_capacity_returns_invalid_request():
    """A vehicle create that omits the required seat capacity is rejected as a shape violation and persists nothing.

    PRD: "**Request shape.** On every endpoint with a request body: required fields present, values of the declared type, enum values drawn from the declared members, every numeric range respected, and a trip request's `destination_stop_id` different from its `origin_stop_id` — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/vehicle_create_missing_seat_capacity_returns_invalid_request
    """
    fixtures.set_clock(CLOCK_STARTUP_UTC)
    zone = fixtures.create_active_zone()

    response = api_client.create_vehicle(
        {"zone_id": zone["id"], "vehicle_code": "V1", "wav_positions": 2},
        ZONE_ADMIN_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    listing = api_client.list_vehicles(
        ZONE_ADMIN_HEADERS, params={"zone_id": zone["id"]}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0
    assertions.assert_row_count(rows, 0)


# ─── Computed fields ───────────────────────────────────────────────────────


def test_trip_request_wav_required_is_computed_and_cannot_be_downgraded_by_body():
    """The effective accessible-handling flag is the OR of the body value and the rider's declared device, so a wheelchair rider's false is ignored.

    PRD: "The effective wheelchair-accessible flag is then resolved and stored on the trip as `wav_required`: it is true when the request body supplied `wav_required` as true **or** when the rider's `mobility_device` is `WHEELCHAIR`."

    Design: Corner/entities/trip_request_wav_required_is_computed_and_cannot_be_downgraded_by_body
    """
    fixtures.set_clock(SERVICE_DAY_OPEN_UTC)
    zone = fixtures.create_active_zone()
    stops = fixtures.build_corridor(zone["id"], indexes=(0, 4))
    wheelchair_rider = fixtures.create_rider(
        zone["id"], "RW", mobility_device="WHEELCHAIR"
    )
    ambulatory_rider = fixtures.create_rider(zone["id"], "RN", mobility_device="NONE")

    wheelchair_trip = fixtures.create_trip(
        zone["id"],
        wheelchair_rider["id"],
        stops[0]["id"],
        stops[4]["id"],
        party_size=1,
        wav_required=False,
        requested_pickup_utc="2026-08-03T07:00:00Z",
    )
    ambulatory_trip = fixtures.create_trip(
        zone["id"],
        ambulatory_rider["id"],
        stops[0]["id"],
        stops[4]["id"],
        party_size=1,
        wav_required=True,
        requested_pickup_utc="2026-08-03T07:30:00Z",
    )

    assert wheelchair_trip["wav_required"] is True
    assert ambulatory_trip["wav_required"] is True
    assert fixtures.refresh_trip(wheelchair_trip["id"])["wav_required"] is True

    # One index step is three minutes, so S0 -> S4 is a twelve-minute direct
    # ride, computed at intake; the offer-time fields stay null until an offer.
    assertions.assert_fields(
        wheelchair_trip,
        baseline_direct_minutes=12,
        match_attempt_count=0,
        status="RECEIVED",
        projected_detour_minutes=None,
        promised_pickup_utc=None,
        quoted_fare_cents=None,
        charged_fare_cents=None,
        applied_cap=None,
    )

    listing = api_client.list_trip_requests(
        DISPATCHER_HEADERS, params={"zone_id": zone["id"], "wav_required": "true"}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 2
    assertions.assert_contains_ids(
        rows, wheelchair_trip["id"], ambulatory_trip["id"]
    )


# ─── System fields ─────────────────────────────────────────────────────────


def test_system_fields_are_server_minted_with_version_one():
    """Two zones created at the same logical instant get distinct server-minted UUIDs and both start at version 1.

    PRD: "`version` (integer): a counter that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row."

    Design: Corner/entities/common_system_fields_are_server_minted_on_every_create
    """
    fixtures.set_clock(CLOCK_STARTUP_UTC)

    first = validate_success(
        api_client.create_service_zone(
            service_zone_payload(
                name="Zone One", zone_code="Z1", on_time_window_minutes=5
            ), ZONE_ADMIN_HEADERS
        ),
        201,
    )
    second = validate_success(
        api_client.create_service_zone(
            service_zone_payload(
                name="Zone Two", zone_code="Z2", on_time_window_minutes=5
            ), ZONE_ADMIN_HEADERS
        ),
        201,
    )

    assertions.assert_versioned_entity(first)
    assertions.assert_versioned_entity(second)
    assert first["id"] != second["id"]
    assert first["version"] == 1
    assert second["version"] == 1


def test_created_at_is_stamped_from_the_logical_clock():
    """The created_at and updated_at stamps on a fresh row read the logical clock, not wall-clock time.

    PRD: "Block windows, transfer buffers, curb-congestion buckets, service dates, fare-cap periods, promised pickups and every stamped timestamp all read a single server-side **logical clock**."

    Design: Corner/entities/common_system_fields_are_server_minted_on_every_create
    """
    fixtures.set_clock(CLOCK_STARTUP_UTC)

    first = validate_success(
        api_client.create_service_zone(
            service_zone_payload(
                name="Zone One", zone_code="Z1", on_time_window_minutes=5
            ), ZONE_ADMIN_HEADERS
        ),
        201,
    )
    second = validate_success(
        api_client.create_service_zone(
            service_zone_payload(
                name="Zone Two", zone_code="Z2", on_time_window_minutes=5
            ), ZONE_ADMIN_HEADERS
        ),
        201,
    )

    assertions.assert_instant_equals(first["created_at"], CLOCK_STARTUP_UTC)
    assertions.assert_instant_equals(first["updated_at"], CLOCK_STARTUP_UTC)
    assertions.assert_instant_equals(second["created_at"], CLOCK_STARTUP_UTC)
    assertions.assert_instant_equals(second["updated_at"], CLOCK_STARTUP_UTC)

    stored = fixtures.refresh_zone(first["id"])
    assertions.assert_instant_equals(stored["created_at"], CLOCK_STARTUP_UTC)


def test_response_envelope_carries_a_server_generated_request_id():
    """Every response carries a server-generated api_request_id prefixed req_ and an ISO 8601 request timestamp.

    PRD: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/entities/common_system_fields_are_server_minted_on_every_create
    """
    fixtures.set_clock(CLOCK_STARTUP_UTC)

    create = api_client.create_service_zone(
        service_zone_payload(
                name="Zone One", zone_code="Z1", on_time_window_minutes=5
            ), ZONE_ADMIN_HEADERS
    )
    zone = validate_success(create, 201)
    read = api_client.get_service_zone(zone["id"], DISPATCHER_HEADERS)
    validate_success(read, 200)

    create_meta = create.json()["meta"]
    read_meta = read.json()["meta"]
    for meta in (create_meta, read_meta):
        assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
        assert is_iso8601_timestamp(meta["api_request_timestamp"]), meta[
            "api_request_timestamp"
        ]
    assert create_meta["api_request_id"] != read_meta["api_request_id"]


# ─── Type, enum and range constraints ──────────────────────────────────────


def test_zone_create_below_the_walk_distance_floor_is_rejected():
    """A zone whose walking-distance standard falls below the 100-metre floor is rejected and never persisted.

    PRD: "The walking-distance standard is `max_walk_meters`, which must be at least 100 and at most 1200; it is the largest walk shed a virtual stop in this zone may advertise and still be approved."

    Design: Corner/entities/enum_and_numeric_range_constraints_are_rejected_at_intake
    """
    fixtures.set_clock(SERVICE_DAY_OPEN_UTC)
    fixtures.create_active_zone()

    response = api_client.create_service_zone(
        service_zone_payload(
            name="Too Short Walk",
            zone_code="TSW",
            max_walk_meters=50,
            on_time_window_minutes=5,
        ),
        ZONE_ADMIN_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    listing = api_client.list_service_zones(ZONE_ADMIN_HEADERS)
    _, meta = validate_paginated(listing)
    assert meta["total_count"] == 1


def test_virtual_stop_create_with_accessibility_outside_the_enum_is_rejected():
    """A virtual stop declaring an accessibility value outside the declared members is rejected and never persisted.

    PRD: "**Request shape.** On every endpoint with a request body: required fields present, values of the declared type, enum values drawn from the declared members, every numeric range respected, and a trip request's `destination_stop_id` different from its `origin_stop_id` — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/enum_and_numeric_range_constraints_are_rejected_at_intake
    """
    fixtures.set_clock(SERVICE_DAY_OPEN_UTC)
    zone = fixtures.create_active_zone()
    fixtures.create_approved_stop(zone["id"], "S0", 0)

    response = api_client.create_virtual_stop(
        {
            "zone_id": zone["id"],
            "stop_code": "S9",
            "corridor_index": 9,
            "walk_shed_meters": 400,
            "accessibility": "RAMP",
        },
        ZONE_ADMIN_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    listing = api_client.list_virtual_stops(
        ZONE_ADMIN_HEADERS, params={"zone_id": zone["id"]}
    )
    _, meta = validate_paginated(listing)
    assert meta["total_count"] == 1


def test_trip_create_with_destination_equal_to_origin_is_rejected():
    """A trip whose destination stop equals its origin stop is rejected as a shape violation and never persisted.

    PRD: "The payload names the `zone_id`, the `rider_id`, the boarding stop as `origin_stop_id`, the alighting stop as `destination_stop_id` — which must differ from the origin, with an equal pair rejected as `ERR_INVALID_REQUEST` — and the rider's desired boarding instant as `requested_pickup_utc`."

    Design: Corner/entities/enum_and_numeric_range_constraints_are_rejected_at_intake
    """
    fixtures.set_clock(SERVICE_DAY_OPEN_UTC)
    zone = fixtures.create_active_zone()
    stop = fixtures.create_approved_stop(zone["id"], "S0", 0)
    rider = fixtures.create_rider(zone["id"], "R1")

    response = api_client.create_trip_request(
        {
            "zone_id": zone["id"],
            "rider_id": rider["id"],
            "origin_stop_id": stop["id"],
            "destination_stop_id": stop["id"],
            "requested_pickup_utc": SERVICE_DAY_PICKUP_UTC,
            "party_size": 1,
        },
        make_rider_headers(rider["id"]),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    listing = api_client.list_trip_requests(
        DISPATCHER_HEADERS, params={"zone_id": zone["id"]}
    )
    _, meta = validate_paginated(listing)
    assert meta["total_count"] == 0


# ─── Ledger immutability ───────────────────────────────────────────────────


def test_fare_ledger_row_carries_no_updated_at_and_no_version():
    """A settled fare-ledger row is readable through both discovery channels and exposes only id and created_at as system fields.

    PRD: "A fare transaction therefore carries only `id` and `created_at`; it has no `updated_at` field and no `version` field at all."

    Design: Corner/entities/fare_transaction_is_immutable_and_exposes_no_mutator
    """
    state = fixtures.setup_completed_trip(
        board_at="2026-08-03T07:00:00Z", complete_at="2026-08-03T07:12:00Z"
    )

    listing = api_client.list_fare_transactions(
        FINANCE_ANALYST_HEADERS, params={"trip_request_id": state["trip"]["id"]}
    )
    rows, meta = validate_paginated(listing)
    assertions.assert_row_count(rows, 1)
    assert meta["total_count"] == 1
    assertions.assert_ledger_row_shape(rows[0])

    single = api_client.get_fare_transaction(rows[0]["id"], FINANCE_ANALYST_HEADERS)
    row = validate_success(single, 200)
    assert row["id"] == rows[0]["id"]
    assertions.assert_ledger_row_shape(row)


def test_fare_ledger_row_records_the_settlement_it_belongs_to():
    """The CHARGE row written by completion names its trip and rider, carries the positive post-multiplier fare, the clock's service date and the settlement's applied cap.

    PRD: "Each row names the `trip_request_id` it belongs to and the `rider_id` whose counters it moves, declares its `kind` as one of `CHARGE`, `TRANSFER_CREDIT`, `CAP_REBATE` or `REFUND`, carries a signed `amount_cents` in which a `CHARGE` is positive and a `TRANSFER_CREDIT`, `CAP_REBATE` or `REFUND` is negative, records the `service_date` as the UTC calendar date of the logical clock at the moment the row was appended, and records the `applied_cap` that bound the settlement the row belongs to as `NONE`, `DAILY` or `WEEKLY`."

    Design: Corner/entities/fare_transaction_is_immutable_and_exposes_no_mutator
    """
    state = fixtures.setup_completed_trip(
        board_at="2026-08-03T07:00:00Z", complete_at="2026-08-03T07:12:00Z"
    )

    listing = api_client.list_fare_transactions(
        FINANCE_ANALYST_HEADERS, params={"trip_request_id": state["trip"]["id"]}
    )
    rows, _ = validate_paginated(listing)

    # A twelve-minute ride is MEDIUM band: 250 base + 75 surcharge, times the
    # FULL multiplier of 1.00, with no connection and 600 cents of daily
    # headroom, so the settlement is a single uncapped 325-cent charge.
    assertions.assert_row_count(rows, 1)
    assertions.assert_ledger_kinds(rows, ["CHARGE"])
    assertions.assert_fields(
        rows[0],
        trip_request_id=state["trip"]["id"],
        rider_id=state["rider"]["id"],
        kind="CHARGE",
        amount_cents=325,
        service_date=SERVICE_DATE,
        applied_cap="NONE",
    )
    assertions.assert_ledger_nets_to(rows, 325)
    assertions.assert_fields(
        state["trip"], charged_fare_cents=325, applied_cap="NONE", fare_status="CHARGED"
    )


# ─── Body foreign keys ─────────────────────────────────────────────────────


def test_vehicle_create_with_unknown_zone_id_returns_service_zone_not_found():
    """An unresolvable zone foreign key in a vehicle create body answers the zone not-found code, not a shape violation.

    PRD: "The same twelve codes are reused when a foreign key supplied in a request body fails to resolve; in that case the fields are checked in the order the endpoint declares its inputs, so the first unresolvable reference in declared order decides the code."

    Design: Corner/entities/body_foreign_keys_must_resolve_before_anything_else_runs
    """
    fixtures.set_clock(SERVICE_DAY_OPEN_UTC)
    fixtures.create_active_zone()

    response = api_client.create_vehicle(
        {
            "zone_id": ABSENT_ZONE_UUID,
            "vehicle_code": "VX",
            "seat_capacity": 6,
            "wav_positions": 0,
        },
        ZONE_ADMIN_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_SERVICE_ZONE_NOT_FOUND.value, 404)

    listing = api_client.list_vehicles(ZONE_ADMIN_HEADERS)
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0
    assertions.assert_row_count(rows, 0)


def test_trip_create_with_unknown_rider_id_returns_rider_not_found():
    """An unresolvable rider foreign key in a trip-intake body answers the rider not-found code and writes no trip.

    PRD: "The same twelve codes are reused when a foreign key supplied in a request body fails to resolve; in that case the fields are checked in the order the endpoint declares its inputs, so the first unresolvable reference in declared order decides the code."

    Design: Corner/entities/body_foreign_keys_must_resolve_before_anything_else_runs
    """
    fixtures.set_clock(SERVICE_DAY_OPEN_UTC)
    zone = fixtures.create_active_zone()
    stops = fixtures.build_corridor(zone["id"], indexes=(0, 4))
    fixtures.create_rider(zone["id"], "R1")

    response = api_client.create_trip_request(
        {
            "zone_id": zone["id"],
            "rider_id": ABSENT_RIDER_UUID,
            "origin_stop_id": stops[0]["id"],
            "destination_stop_id": stops[4]["id"],
            "requested_pickup_utc": SERVICE_DAY_PICKUP_UTC,
            "party_size": 1,
        },
        DISPATCHER_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_RIDER_NOT_FOUND.value, 404)

    listing = api_client.list_trip_requests(DISPATCHER_HEADERS)
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0
    assertions.assert_row_count(rows, 0)


# ─── Cross-zone consistency ────────────────────────────────────────────────


def test_cross_zone_stop_reference_on_trip_create_is_a_zone_mismatch():
    """A trip in one zone naming an approved stop that belongs to another zone is a zone mismatch, not a not-found.

    PRD: "**Cross-zone consistency.** On virtual-stop create, transit-connection create, vehicle-block create, trip-request create and pool-assignment create, every referenced stop, connection, rider, vehicle, driver and block must belong to the same zone as the operation, and on pool-assignment create the trip's `zone_id` must equal the block's `zone_id` — otherwise `ERR_ZONE_MISMATCH`."

    Design: Corner/entities/cross_zone_stop_reference_on_trip_create_is_a_zone_mismatch
    """
    fixtures.set_clock(SERVICE_DAY_OPEN_UTC)
    zone_a = fixtures.create_active_zone(name="Riverbend A", zone_code="RBM-A")
    zone_b = fixtures.create_active_zone(name="Riverbend B", zone_code="RBM-B")
    stop_a0 = fixtures.create_approved_stop(zone_a["id"], "A0", 0)
    stop_b4 = fixtures.create_approved_stop(zone_b["id"], "B4", 4)
    rider_a = fixtures.create_rider(zone_a["id"], "RA")

    response = api_client.create_trip_request(
        {
            "zone_id": zone_a["id"],
            "rider_id": rider_a["id"],
            "origin_stop_id": stop_a0["id"],
            "destination_stop_id": stop_b4["id"],
            "requested_pickup_utc": SERVICE_DAY_PICKUP_UTC,
            "party_size": 1,
        },
        make_rider_headers(rider_a["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ZONE_MISMATCH.value, 409)

    listing = api_client.list_trip_requests(
        DISPATCHER_HEADERS, params={"zone_id": zone_a["id"]}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0
    assertions.assert_row_count(rows, 0)
    assert fixtures.refresh_stop(stop_b4["id"])["zone_id"] == zone_b["id"]
