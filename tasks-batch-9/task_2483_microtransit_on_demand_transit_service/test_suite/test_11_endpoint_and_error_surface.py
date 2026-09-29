"""Endpoint surface and rejection surface of the microtransit on-demand API.

The endpoint tests walk the create / read / read-many shape of the flat topology,
the action endpoints that are really state machines, the two-sided link endpoint
and the logical clock that every stamped timestamp reads. The error tests walk
the first six rungs of the rejection order in PRD §2.9 — headers, role, identity,
path existence, body references and ownership — plus the state-machine rejection
a driver-status endpoint raises when asked to re-assert its current value.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, factories, fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import ABSENT_UUID
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    DISPATCHER_HEADERS,
    FINANCE_ANALYST_HEADERS,
    ZONE_ADMIN_HEADERS,
    headers_without_identity,
    make_driver_headers,
    make_rider_headers,
)

# ═══════════════════════════════════════════════════════════════════════════
# Endpoint surface
# ═══════════════════════════════════════════════════════════════════════════


class TestTransitConnectionSurface:
    """Create, read-one and filtered read-many for the transit-connection
    collection, which has no update or delete operation at all."""

    @staticmethod
    def _zone_with_platform_stop():
        fixtures.set_clock("2026-08-03T05:00:00Z", headers=ZONE_ADMIN_HEADERS)
        zone = fixtures.create_active_zone()
        stop = fixtures.create_approved_stop(zone["id"], "S0", 0)
        return zone, stop

    def test_transit_connection_create_and_read_one_round_trip(self):
        """Registering rail and bus departures on one stop answers 201 and both rows read back verbatim.

        PRD: "A connection names its `zone_id` and the `stop_id` of the virtual stop co-located with the rail platform or bus bay, declares its `mode` as either `RAIL` or `BUS`, records the agency's `route_code` for the line, and states the `scheduled_departure_utc` instant of the fixed-route trip."

        Design: Corner/endpoints/transit_connection_create_read_and_list_round_trip
        """
        zone, stop = self._zone_with_platform_stop()

        rail = validate_success(
            api_client.create_transit_connection(
                factories.transit_connection_payload(
                    zone["id"],
                    stop["id"],
                    mode="RAIL",
                    route_code="ORANGE-IB",
                    scheduled_departure_utc="2026-08-03T07:00:00Z",
                    guaranteed_transfer_buffer_minutes=10,
                    transfer_credit_cents=80,
                ),
                ZONE_ADMIN_HEADERS,
            ),
            201,
        )
        bus = validate_success(
            api_client.create_transit_connection(
                factories.transit_connection_payload(
                    zone["id"],
                    stop["id"],
                    mode="BUS",
                    route_code="R12",
                    scheduled_departure_utc="2026-08-03T07:30:00Z",
                    guaranteed_transfer_buffer_minutes=5,
                    transfer_credit_cents=40,
                ),
                ZONE_ADMIN_HEADERS,
            ),
            201,
        )

        assertions.assert_versioned_entity(rail)
        assertions.assert_fields(
            rail,
            zone_id=zone["id"],
            stop_id=stop["id"],
            mode="RAIL",
            route_code="ORANGE-IB",
            guaranteed_transfer_buffer_minutes=10,
            transfer_credit_cents=80,
            version=1,
        )
        assertions.assert_instant_equals(
            rail["scheduled_departure_utc"], "2026-08-03T07:00:00Z"
        )
        assertions.assert_fields(
            bus,
            mode="BUS",
            route_code="R12",
            guaranteed_transfer_buffer_minutes=5,
            transfer_credit_cents=40,
            version=1,
        )

        read = validate_success(
            api_client.get_transit_connection(rail["id"], DISPATCHER_HEADERS), 200
        )
        assertions.assert_fields(
            read,
            id=rail["id"],
            mode="RAIL",
            route_code="ORANGE-IB",
            transfer_credit_cents=80,
        )

    def test_transit_connection_list_separates_the_two_modes(self):
        """The mode filter isolates the bus departure while the zone filter still counts both.

        PRD: "Transit connections filter on `zone_id`, `stop_id` and `mode`."

        Design: Corner/endpoints/transit_connection_create_read_and_list_round_trip
        """
        zone, stop = self._zone_with_platform_stop()

        rail = fixtures.create_connection(
            zone["id"],
            stop["id"],
            mode="RAIL",
            route_code="ORANGE-IB",
            scheduled_departure_utc="2026-08-03T07:00:00Z",
            guaranteed_transfer_buffer_minutes=10,
            transfer_credit_cents=80,
        )
        bus = fixtures.create_connection(
            zone["id"],
            stop["id"],
            mode="BUS",
            route_code="R12",
            scheduled_departure_utc="2026-08-03T07:30:00Z",
            guaranteed_transfer_buffer_minutes=5,
            transfer_credit_cents=40,
        )

        rows, meta = validate_paginated(
            api_client.list_transit_connections(
                DISPATCHER_HEADERS, params={"zone_id": zone["id"], "mode": "BUS"}
            )
        )
        assertions.assert_row_count(rows, 1)
        assert rows[0]["id"] == bus["id"], rows[0]["id"]
        assert meta["total_count"] == 1, meta
        assert meta["has_more"] is False, meta

        all_rows, all_meta = validate_paginated(
            api_client.list_transit_connections(
                DISPATCHER_HEADERS, params={"zone_id": zone["id"]}
            )
        )
        assert all_meta["total_count"] == 2, all_meta
        assertions.assert_contains_ids(all_rows, rail["id"], bus["id"])


def test_vehicle_status_walks_the_maintenance_cycle_then_locks_on_retired():
    """AVAILABLE to IN_MAINTENANCE to AVAILABLE to RETIRED all succeed, and the move back out of RETIRED is a 409.

    PRD: "A requested move that is not one of the four — for instance any move out of `RETIRED`, which is terminal — is rejected with `ERR_INVALID_VEHICLE_STATE`, and so is an attempt to retire a vehicle that a scheduled or open block still depends on."

    Design: Corner/endpoints/vehicle_status_action_walks_the_maintenance_cycle_then_locks_on_retired
    """
    fixtures.set_clock("2026-08-03T05:00:00Z", headers=ZONE_ADMIN_HEADERS)
    zone = fixtures.create_active_zone()
    vehicle = fixtures.create_vehicle(zone["id"], "V1", seat_capacity=6, wav_positions=2)
    assert vehicle["status"] == "AVAILABLE", vehicle["status"]
    assert vehicle["version"] == 1, vehicle["version"]

    # The maintenance capability is shared, so alternate the two authorised roles.
    in_maintenance = validate_success(
        api_client.set_vehicle_status(
            vehicle["id"], {"status": "IN_MAINTENANCE"}, DISPATCHER_HEADERS
        ),
        200,
    )
    assertions.assert_fields(in_maintenance, status="IN_MAINTENANCE", version=2)

    back_available = validate_success(
        api_client.set_vehicle_status(
            vehicle["id"], {"status": "AVAILABLE"}, ZONE_ADMIN_HEADERS
        ),
        200,
    )
    assertions.assert_fields(back_available, status="AVAILABLE", version=3)

    retired = validate_success(
        api_client.set_vehicle_status(
            vehicle["id"], {"status": "RETIRED"}, ZONE_ADMIN_HEADERS
        ),
        200,
    )
    assertions.assert_fields(retired, status="RETIRED", version=4)

    validate_error(
        api_client.set_vehicle_status(
            vehicle["id"], {"status": "AVAILABLE"}, ZONE_ADMIN_HEADERS
        ),
        ApiErrorId.ERR_INVALID_VEHICLE_STATE.value,
        409,
    )

    final = validate_success(
        api_client.get_vehicle(vehicle["id"], DISPATCHER_HEADERS), 200
    )
    assertions.assert_fields(final, status="RETIRED", version=retired["version"])
    assertions.assert_version_unchanged(retired, final)


class TestPoolAssignmentLink:
    """The manual-dispatch endpoint links a trip to a block through two foreign
    keys, so both sides have to resolve before anything is written."""

    def test_pool_assignment_link_reports_the_unresolved_side(self):
        """An absent trip id is a trip-request 404 and an absent block id is a vehicle-block 404.

        PRD: "The same twelve codes are reused when a foreign key supplied in a request body fails to resolve; in that case the fields are checked in the order the endpoint declares its inputs, so the first unresolvable reference in declared order decides the code."

        Design: Corner/endpoints/pool_assignment_link_requires_both_sides_to_exist
        """
        state = fixtures.setup_received_trip(
            state=fixtures.setup_dispatch_ready(clock_at="2026-08-03T06:00:00Z"),
            origin_index=0,
            destination_index=4,
        )
        block_version = fixtures.block_version(state["block"]["id"])

        validate_error(
            api_client.create_pool_assignment(
                factories.pool_assignment_payload(
                    ABSENT_UUID, state["block"]["id"], block_version
                ),
                DISPATCHER_HEADERS,
            ),
            ApiErrorId.ERR_TRIP_REQUEST_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.create_pool_assignment(
                factories.pool_assignment_payload(
                    state["trip"]["id"], ABSENT_UUID, block_version
                ),
                DISPATCHER_HEADERS,
            ),
            ApiErrorId.ERR_VEHICLE_BLOCK_NOT_FOUND.value,
            404,
        )

        # Neither rejected link wrote anything.
        rows, meta = validate_paginated(
            api_client.list_pool_assignments(
                DISPATCHER_HEADERS, params={"trip_request_id": state["trip"]["id"]}
            )
        )
        assertions.assert_row_count(rows, 0)
        assert meta["total_count"] == 0, meta
        assertions.assert_trip_state(
            fixtures.refresh_trip(state["trip"]["id"]), "RECEIVED", "UNPRICED"
        )

    def test_pool_assignment_link_writes_both_directions(self):
        """A resolvable link answers 201 and books the trip onto the block from both sides.

        PRD: "The resulting offer carries `offer_origin` of `MANUAL_DISPATCH` and, because no ranking took place, a `match_score` of null; everything else about the resulting offer and the resulting trip state is identical to an automatic win, including the `UNPRICED → QUOTED` fare move and the block's capacity and version updates."

        Design: Corner/endpoints/pool_assignment_link_requires_both_sides_to_exist
        """
        state = fixtures.setup_received_trip(
            state=fixtures.setup_dispatch_ready(clock_at="2026-08-03T06:00:00Z"),
            origin_index=0,
            destination_index=4,
        )
        block_version = fixtures.block_version(state["block"]["id"])

        assignment = validate_success(
            api_client.create_pool_assignment(
                factories.pool_assignment_payload(
                    state["trip"]["id"], state["block"]["id"], block_version
                ),
                DISPATCHER_HEADERS,
            ),
            201,
        )
        assertions.assert_versioned_entity(assignment)
        assertions.assert_fields(
            assignment,
            trip_request_id=state["trip"]["id"],
            block_id=state["block"]["id"],
            offer_origin="MANUAL_DISPATCH",
            match_score=None,
            seq_pickup=1,
            seats_held=1,
            wav_positions_held=0,
        )
        assertions.assert_assignment_state(assignment, "OFFERED")

        trip = fixtures.refresh_trip(state["trip"]["id"])
        assertions.assert_trip_state(trip, "OFFERED", "QUOTED")
        assert trip["assigned_block_id"] == state["block"]["id"], trip[
            "assigned_block_id"
        ]


def test_logical_clock_endpoint_drives_every_server_timestamp():
    """Rewinding the logical clock between two creates makes the later row's created_at the earlier instant.

    PRD: "At server start-up the logical clock reads exactly `2026-08-01T00:00:00Z`, and it continues to read that instant until it is moved; it never falls back to real wall-clock time."

    Design: Corner/endpoints/logical_clock_endpoint_drives_every_server_timestamp
    """
    validate_success(
        api_client.set_current_utc(
            factories.clock_payload("2026-08-03T09:00:00Z"), ZONE_ADMIN_HEADERS
        ),
        200,
    )
    zone = fixtures.create_active_zone()
    first = fixtures.create_vehicle(zone["id"], "V1", seat_capacity=6, wav_positions=2)
    assertions.assert_instant_equals(first["created_at"], "2026-08-03T09:00:00Z")

    rewound = validate_success(
        api_client.set_current_utc(
            factories.clock_payload("2026-08-03T08:00:00Z"), DISPATCHER_HEADERS
        ),
        200,
    )
    assertions.assert_instant_equals(rewound["current_utc"], "2026-08-03T08:00:00Z")

    second = fixtures.create_vehicle(zone["id"], "V2", seat_capacity=4, wav_positions=0)
    assertions.assert_instant_equals(second["created_at"], "2026-08-03T08:00:00Z")

    # The row created second carries the earlier instant, which no wall clock
    # could produce.
    assert assertions.normalize_instant(
        second["created_at"]
    ) < assertions.normalize_instant(first["created_at"]), (
        f"{second['created_at']} should precede {first['created_at']}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Rejection surface
# ═══════════════════════════════════════════════════════════════════════════


def test_calls_without_identity_headers_are_rejected():
    """A header-less read is 401 even on an all-roles endpoint and even when the path id names no row.

    PRD: "If either header is absent or present but empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined."

    Design: Corner/errors/calls_without_identity_headers_are_rejected
    """
    fixtures.set_clock("2026-08-01T00:00:00Z", headers=ZONE_ADMIN_HEADERS)
    zone = fixtures.create_zone()

    validate_error(
        api_client.get_service_zone(zone["id"], headers_without_identity()),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    # Authentication is examined before path existence, so the absent id still
    # answers 401 rather than 404.
    validate_error(
        api_client.get_service_zone(ABSENT_UUID, headers_without_identity()),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )

    with_headers = validate_success(
        api_client.get_service_zone(zone["id"], ZONE_ADMIN_HEADERS), 200
    )
    assertions.assert_fields(with_headers, id=zone["id"], status="DRAFT")


def test_wrong_role_on_an_exclusive_endpoint_is_rejected():
    """A Dispatcher defining a zone and a Rider opening a block are both 403 despite well-formed inputs.

    PRD: "If `X-User-Role` is not one of those six strings, or is one of them but is not among the roles authorised for the endpoint being called (see the Authorized Role(s) column in Section 4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/errors/wrong_role_on_an_exclusive_endpoint_is_rejected
    """
    state = fixtures.setup_dispatch_ready(
        clock_at="2026-08-03T05:00:00Z", open_the_block=False
    )
    assertions.assert_block_state(state["block"], "SCHEDULED")

    validate_error(
        api_client.create_service_zone(
            factories.service_zone_payload(name="Dispatcher Zone", zone_code="DZ"),
            DISPATCHER_HEADERS,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    validate_error(
        api_client.open_vehicle_block(
            state["block"]["id"], make_rider_headers(state["rider"]["id"])
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )

    _, meta = validate_paginated(api_client.list_service_zones(ZONE_ADMIN_HEADERS))
    assert meta["total_count"] == 1, meta
    assertions.assert_block_state(fixtures.refresh_block(state["block"]["id"]), "SCHEDULED")


def test_entity_backed_identity_that_resolves_to_nothing_is_rejected():
    """A Rider id that names no rider row, and a rider id presented as a driver id, are both 403.

    PRD: "A caller acting as `Rider` whose `X-User-ID` does not name an existing `Rider` row, or acting as `DriverUser` whose `X-User-ID` does not name an existing `Driver` row, is rejected with `ERR_IDENTITY_NOT_FOUND` (HTTP 403)."

    Design: Corner/errors/entity_backed_identity_that_resolves_to_nothing_is_rejected
    """
    state = fixtures.setup_offered_trip(
        state=fixtures.setup_dispatch_ready(clock_at="2026-08-03T06:00:00Z"),
        origin_index=0,
        destination_index=4,
        manual=True,
    )

    validate_error(
        api_client.create_trip_request(
            factories.trip_request_payload(
                state["zone"]["id"],
                state["rider"]["id"],
                state["stops"][0]["id"],
                state["stops"][4]["id"],
                requested_pickup_utc="2026-08-03T08:00:00Z",
            ),
            make_rider_headers(ABSENT_UUID),
        ),
        ApiErrorId.ERR_IDENTITY_NOT_FOUND.value,
        403,
    )
    # The rider id is a real row, but it resolves in the wrong backing table.
    validate_error(
        api_client.accept_pool_assignment(
            state["assignment"]["id"], make_driver_headers(state["rider"]["id"])
        ),
        ApiErrorId.ERR_IDENTITY_NOT_FOUND.value,
        403,
    )

    _, meta = validate_paginated(
        api_client.list_trip_requests(
            DISPATCHER_HEADERS, params={"zone_id": state["zone"]["id"]}
        )
    )
    assert meta["total_count"] == 1, meta
    assertions.assert_assignment_state(
        fixtures.refresh_assignment(state["assignment"]["id"]), "OFFERED"
    )


class TestOwnershipOnEntityBackedRoles:
    """Ownership is the sixth rung of the rejection order, so a valid principal
    reaching for another principal's row is 403 rather than 404."""

    @staticmethod
    def _offered_state():
        return fixtures.setup_offered_trip(
            state=fixtures.setup_dispatch_ready(clock_at="2026-08-03T06:00:00Z"),
            origin_index=0,
            destination_index=4,
            manual=True,
        )

    def test_rider_cannot_touch_another_riders_trip(self):
        """A second rider cannot cancel, read, or intake a trip that belongs to the first rider.

        PRD: "A `Rider` may create a trip request only for themselves (the `rider_id` in the payload must equal `X-User-ID`), may cancel only their own trip, and may read only a trip request, a pool assignment or a fare-ledger row that belongs to them."

        Design: Corner/errors/rider_and_driver_cannot_touch_another_principals_rows
        """
        state = self._offered_state()
        other_rider = fixtures.create_rider(state["zone"]["id"], "R2")
        other_headers = make_rider_headers(other_rider["id"])

        validate_error(
            api_client.cancel_trip_request(
                state["trip"]["id"], other_headers, payload={"note": "not my trip"}
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
            403,
        )
        validate_error(
            api_client.get_trip_request(state["trip"]["id"], other_headers),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
            403,
        )
        validate_error(
            api_client.create_trip_request(
                factories.trip_request_payload(
                    state["zone"]["id"],
                    state["rider"]["id"],
                    state["stops"][0]["id"],
                    state["stops"][4]["id"],
                    requested_pickup_utc="2026-08-03T08:00:00Z",
                ),
                other_headers,
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
            403,
        )

        assertions.assert_trip_state(
            fixtures.refresh_trip(state["trip"]["id"]), "OFFERED", "QUOTED"
        )
        assertions.assert_assignment_state(
            fixtures.refresh_assignment(state["assignment"]["id"]), "OFFERED"
        )

    def test_driver_cannot_accept_an_offer_on_another_drivers_block(self):
        """A second, perfectly valid driver in the same zone cannot accept an offer on the first driver's block.

        PRD: "All four driver actions are restricted to the `DriverUser` role and all four require that `X-User-ID` equal the `driver_id` of the block the assignment sits on, with a mismatch reported as `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/errors/rider_and_driver_cannot_touch_another_principals_rows
        """
        state = self._offered_state()
        other_driver = fixtures.create_driver(
            state["zone"]["id"], "D2", wav_certified=True
        )
        assert other_driver["status"] == "ACTIVE", other_driver["status"]

        validate_error(
            api_client.accept_pool_assignment(
                state["assignment"]["id"], make_driver_headers(other_driver["id"])
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
            403,
        )
        validate_error(
            api_client.get_pool_assignment(
                state["assignment"]["id"], make_driver_headers(other_driver["id"])
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
            403,
        )

        assertions.assert_assignment_state(
            fixtures.refresh_assignment(state["assignment"]["id"]), "OFFERED"
        )
        assertions.assert_trip_state(
            fixtures.refresh_trip(state["trip"]["id"]), "OFFERED", "QUOTED"
        )


# One probe per collection: the read method, the matching list method, the
# collection's own not-found code and the role the read is issued under.
PATH_ID_PROBES = [
    (
        "get_transit_connection",
        "list_transit_connections",
        ApiErrorId.ERR_TRANSIT_CONNECTION_NOT_FOUND,
        ZONE_ADMIN_HEADERS,
    ),
    ("get_vehicle", "list_vehicles", ApiErrorId.ERR_VEHICLE_NOT_FOUND, ZONE_ADMIN_HEADERS),
    ("get_driver", "list_drivers", ApiErrorId.ERR_DRIVER_NOT_FOUND, ZONE_ADMIN_HEADERS),
    (
        "get_demand_forecast",
        "list_demand_forecasts",
        ApiErrorId.ERR_DEMAND_FORECAST_NOT_FOUND,
        ZONE_ADMIN_HEADERS,
    ),
    (
        "get_vehicle_block",
        "list_vehicle_blocks",
        ApiErrorId.ERR_VEHICLE_BLOCK_NOT_FOUND,
        DISPATCHER_HEADERS,
    ),
    (
        "get_pool_assignment",
        "list_pool_assignments",
        ApiErrorId.ERR_POOL_ASSIGNMENT_NOT_FOUND,
        DISPATCHER_HEADERS,
    ),
    (
        "get_fare_transaction",
        "list_fare_transactions",
        ApiErrorId.ERR_FARE_TRANSACTION_NOT_FOUND,
        FINANCE_ANALYST_HEADERS,
    ),
    (
        "get_subsidy_report",
        "list_subsidy_reports",
        ApiErrorId.ERR_SUBSIDY_REPORT_NOT_FOUND,
        AUDITOR_HEADERS,
    ),
]


@pytest.mark.parametrize(
    "read_method,list_method,error_id,headers",
    PATH_ID_PROBES,
    ids=[probe[2].value for probe in PATH_ID_PROBES],
)
def test_unknown_path_ids_across_every_collection_are_not_found(
    read_method, list_method, error_id, headers
):
    """Each collection answers a well-formed but absent path id with its own distinct 404 code.

    PRD: "The twelve not-found codes are `ERR_SERVICE_ZONE_NOT_FOUND`, `ERR_VIRTUAL_STOP_NOT_FOUND`, `ERR_TRANSIT_CONNECTION_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_RIDER_NOT_FOUND`, `ERR_DEMAND_FORECAST_NOT_FOUND`, `ERR_VEHICLE_BLOCK_NOT_FOUND`, `ERR_TRIP_REQUEST_NOT_FOUND`, `ERR_POOL_ASSIGNMENT_NOT_FOUND`, `ERR_FARE_TRANSACTION_NOT_FOUND` and `ERR_SUBSIDY_REPORT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/unknown_path_ids_across_every_collection_are_not_found
    """
    fixtures.set_clock("2026-08-01T00:00:00Z", headers=ZONE_ADMIN_HEADERS)

    validate_error(
        getattr(api_client, read_method)(ABSENT_UUID, headers), error_id.value, 404
    )

    rows, meta = validate_paginated(getattr(api_client, list_method)(headers))
    assertions.assert_row_count(rows, 0)
    assert meta["total_count"] == 0, meta


def test_driver_status_transition_to_its_current_value_is_a_state_error():
    """Re-asserting a driver's current status is a 409, while the declared reverse move succeeds.

    PRD: "Both directions set `status` to the requested value and advance the driver's `version` by 1; a move that is not declared from the current state is rejected with `ERR_INVALID_DRIVER_STATE`."

    Design: Corner/errors/driver_status_transition_to_its_current_value_is_a_state_error
    """
    fixtures.set_clock("2026-08-03T05:00:00Z", headers=ZONE_ADMIN_HEADERS)
    zone = fixtures.create_active_zone()
    driver = fixtures.create_driver(zone["id"], "D1", wav_certified=True)
    assertions.assert_fields(
        driver, status="ACTIVE", consecutive_decline_count=0, version=1
    )

    validate_error(
        api_client.set_driver_status(
            driver["id"], {"status": "ACTIVE"}, DISPATCHER_HEADERS
        ),
        ApiErrorId.ERR_INVALID_DRIVER_STATE.value,
        409,
    )
    unchanged = get_success_data(api_client.get_driver(driver["id"], ZONE_ADMIN_HEADERS))
    assertions.assert_fields(unchanged, status="ACTIVE", version=1)

    suspended = validate_success(
        api_client.set_driver_status(
            driver["id"], {"status": "SUSPENDED"}, DISPATCHER_HEADERS
        ),
        200,
    )
    assertions.assert_fields(
        suspended, status="SUSPENDED", version=2, consecutive_decline_count=0
    )

    validate_error(
        api_client.set_driver_status(
            driver["id"], {"status": "SUSPENDED"}, DISPATCHER_HEADERS
        ),
        ApiErrorId.ERR_INVALID_DRIVER_STATE.value,
        409,
    )

    reinstated = validate_success(
        api_client.set_driver_status(
            driver["id"], {"status": "ACTIVE"}, ZONE_ADMIN_HEADERS
        ),
        200,
    )
    assertions.assert_fields(
        reinstated, status="ACTIVE", version=3, consecutive_decline_count=0
    )
