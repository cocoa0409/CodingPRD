"""Role admission across the six recognised roles, the two version-guarded
writes, and the immediacy of cascade visibility.

The three role families exercise the authorised set of each endpoint from both
sides: every role driving its own exclusive operations, every crossed attempt
being refused, and the shared surface accepting each of its permitted roles.
The concurrency pair pins the stale-version rejections of PRD §2.8, and the last
test pins the same-request visibility promised by PRD §2.10.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    demand_forecast_payload,
    driver_payload,
    pool_assignment_payload,
    rider_payload,
    service_zone_payload,
    subsidy_report_payload,
    transit_connection_payload,
    trip_request_payload,
    vehicle_block_payload,
    vehicle_payload,
    virtual_stop_payload,
)
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    AUDITOR_ID,
    DISPATCHER_HEADERS,
    FINANCE_ANALYST_HEADERS,
    FINANCE_ANALYST_ID,
    ZONE_ADMIN_HEADERS,
    make_driver_headers,
    make_rider_headers,
)

# The reporting period every subsidy report in this file covers. July 2026 holds
# no vehicle block and no trip, so certification is never gated by an
# unfinalised block.
JULY_PERIOD = {
    "period_start_date": "2026-07-01",
    "period_end_date": "2026-07-31",
}


# ─── every role drives its own exclusive operations ────────────────────────


def test_each_role_drives_its_own_exclusive_operations_end_to_end():
    """One unbroken chain lets each of the six roles run the operations only it is authorised for.

    PRD: "If `X-User-Role` is not one of those six strings, or is one of them but is not among the roles authorised for the endpoint being called (see the Authorized Role(s) column in Section 4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations
    """
    fixtures.set_clock("2026-08-03T05:00:00Z", headers=ZONE_ADMIN_HEADERS)

    # ZoneAdmin plans the zone, its corridor, its reference data and the forecast.
    zone = validate_success(
        api_client.create_service_zone(service_zone_payload(), ZONE_ADMIN_HEADERS), 201
    )
    zone_id = zone["id"]
    zone = validate_success(
        api_client.activate_service_zone(zone_id, ZONE_ADMIN_HEADERS), 200
    )
    assertions.assert_fields(zone, status="ACTIVE")
    zone_version = zone["version"]

    origin = validate_success(
        api_client.create_virtual_stop(
            virtual_stop_payload(zone_id, "S0", 0), ZONE_ADMIN_HEADERS
        ),
        201,
    )
    origin = validate_success(
        api_client.approve_virtual_stop(origin["id"], ZONE_ADMIN_HEADERS), 200
    )
    assertions.assert_fields(origin, status="APPROVED")
    destination = validate_success(
        api_client.create_virtual_stop(
            virtual_stop_payload(zone_id, "S4", 4), ZONE_ADMIN_HEADERS
        ),
        201,
    )
    destination = validate_success(
        api_client.approve_virtual_stop(destination["id"], ZONE_ADMIN_HEADERS), 200
    )
    assertions.assert_fields(destination, status="APPROVED")

    validate_success(
        api_client.create_transit_connection(
            transit_connection_payload(zone_id, origin["id"]), ZONE_ADMIN_HEADERS
        ),
        201,
    )
    vehicle = validate_success(
        api_client.create_vehicle(vehicle_payload(zone_id, "V1"), ZONE_ADMIN_HEADERS),
        201,
    )
    driver = validate_success(
        api_client.create_driver(driver_payload(zone_id, "D1"), ZONE_ADMIN_HEADERS), 201
    )
    rider = validate_success(
        api_client.create_rider(rider_payload(zone_id, "R1"), ZONE_ADMIN_HEADERS), 201
    )
    forecast = validate_success(
        api_client.create_demand_forecast(
            demand_forecast_payload(zone_id, zone_version), ZONE_ADMIN_HEADERS
        ),
        201,
    )
    # A four-hour window serves 16 trips per block, so 10 forecast trips need one
    # base block, and a peak factor of 1.20 needs no surge block at all.
    assertions.assert_fields(
        forecast, state="PUBLISHED", required_base_blocks=1, required_surge_blocks=0
    )

    # Dispatcher schedules and opens the block.
    block = validate_success(
        api_client.create_vehicle_block(
            vehicle_block_payload(zone_id, vehicle["id"], driver["id"]),
            DISPATCHER_HEADERS,
        ),
        201,
    )
    block = validate_success(
        api_client.open_vehicle_block(block["id"], DISPATCHER_HEADERS), 200
    )
    assertions.assert_block_state(block, "OPEN")
    block_version = block["version"]

    # The Rider files her own trip, the Dispatcher hand-dispatches it and the
    # DriverUser accepts it.
    own_trip = validate_success(
        api_client.create_trip_request(
            trip_request_payload(zone_id, rider["id"], origin["id"], destination["id"]),
            make_rider_headers(rider["id"]),
        ),
        201,
    )
    manual_offer = validate_success(
        api_client.create_pool_assignment(
            pool_assignment_payload(own_trip["id"], block["id"], block_version),
            DISPATCHER_HEADERS,
        ),
        201,
    )
    manual_offer = validate_success(
        api_client.accept_pool_assignment(
            manual_offer["id"], make_driver_headers(driver["id"])
        ),
        200,
    )
    assertions.assert_assignment_state(manual_offer, "ACCEPTED")
    assertions.assert_trip_state(fixtures.refresh_trip(own_trip["id"]), "ASSIGNED")

    # The Dispatcher files a second trip on the rider's behalf and matches it.
    agent_trip = validate_success(
        api_client.create_trip_request(
            trip_request_payload(
                zone_id,
                rider["id"],
                origin["id"],
                destination["id"],
                requested_pickup_utc="2026-08-03T08:00:00Z",
            ),
            DISPATCHER_HEADERS,
        ),
        201,
    )
    agent_trip = validate_success(
        api_client.match_trip_request(agent_trip["id"], DISPATCHER_HEADERS), 200
    )
    assertions.assert_trip_state(agent_trip, "OFFERED")
    assertions.assert_fields(agent_trip, match_attempt_count=1)
    offers, offers_meta = validate_paginated(
        api_client.list_pool_assignments(
            DISPATCHER_HEADERS, params={"trip_request_id": agent_trip["id"]}
        )
    )
    assert offers_meta["total_count"] == 1, offers_meta
    # A zero detour scores 0, a BASE block adds no surge penalty, no securement
    # penalty applies and four remaining seats score 8.
    assertions.assert_fields(offers[0], offer_origin="AUTO_MATCH", match_score=8)

    # The FinanceAnalyst prepares and files the report; only the auditor certifies.
    report = validate_success(
        api_client.create_subsidy_report(
            subsidy_report_payload(zone_id, variant="PROVISIONAL", **JULY_PERIOD),
            FINANCE_ANALYST_HEADERS,
        ),
        201,
    )
    report = validate_success(
        api_client.submit_subsidy_report(report["id"], FINANCE_ANALYST_HEADERS), 200
    )
    assertions.assert_report_state(report, "SUBMITTED")
    report = validate_success(
        api_client.certify_subsidy_report(
            report["id"], AUDITOR_HEADERS, {"note": "period reviewed"}
        ),
        200,
    )
    assertions.assert_report_state(report, "CERTIFIED")
    assertions.assert_fields(
        report,
        submitted_by_user_id=FINANCE_ANALYST_ID,
        certified_by_user_id=AUDITOR_ID,
        total_trips=0,
        subsidy_per_trip_cents=0,
    )


# ─── no role reaches another role's exclusive operations ───────────────────


def _crossed_role_state() -> dict:
    """An active zone with a proposed stop, an open block, a received trip, a
    DRAFT report and a second SUBMITTED report — one live target for each
    crossed-role attempt below."""
    fixtures.set_clock("2026-08-03T06:00:00Z", headers=ZONE_ADMIN_HEADERS)
    zone = fixtures.create_zone()
    zone = fixtures.activate_zone(zone["id"])
    origin = fixtures.create_approved_stop(zone["id"], "S0", 0)
    destination = fixtures.create_approved_stop(zone["id"], "S4", 4)
    proposed = fixtures.create_stop(zone["id"], "S1", 1)
    vehicle = fixtures.create_vehicle(zone["id"], "V1")
    driver = fixtures.create_driver(zone["id"], "D1")
    rider = fixtures.create_rider(zone["id"], "R1")
    block = fixtures.open_block(
        fixtures.create_block(zone["id"], vehicle["id"], driver["id"])["id"]
    )
    trip = fixtures.create_trip(
        zone["id"], rider["id"], origin["id"], destination["id"]
    )
    draft_report = fixtures.create_report(
        zone["id"], variant="PROVISIONAL", **JULY_PERIOD
    )
    filed_report = fixtures.create_report(zone["id"], variant="FINAL", **JULY_PERIOD)
    filed_report = fixtures.submit_report(filed_report["id"])
    return {
        "zone": zone,
        "proposed": proposed,
        "vehicle": vehicle,
        "driver": driver,
        "rider": rider,
        "block": block,
        "trip": trip,
        "draft_report": draft_report,
        "filed_report": filed_report,
    }


def _attempt_dispatcher_approves_stop(state):
    return api_client.approve_virtual_stop(
        state["proposed"]["id"], DISPATCHER_HEADERS
    )


def _verify_stop_untouched(state):
    assertions.assert_fields(
        fixtures.refresh_stop(state["proposed"]["id"]), status="PROPOSED"
    )


def _attempt_zone_admin_creates_offer(state):
    return api_client.create_pool_assignment(
        pool_assignment_payload(
            state["trip"]["id"], state["block"]["id"], state["block"]["version"]
        ),
        ZONE_ADMIN_HEADERS,
    )


def _verify_no_offer_exists(state):
    rows, meta = validate_paginated(
        api_client.list_pool_assignments(
            DISPATCHER_HEADERS, params={"block_id": state["block"]["id"]}
        )
    )
    assert meta["total_count"] == 0, meta
    assert rows == [], rows
    trip = fixtures.refresh_trip(state["trip"]["id"])
    assertions.assert_trip_state(trip, "RECEIVED")
    assertions.assert_null_fields(trip, "assigned_block_id")


def _attempt_dispatcher_publishes_forecast(state):
    return api_client.create_demand_forecast(
        demand_forecast_payload(state["zone"]["id"], state["zone"]["version"]),
        DISPATCHER_HEADERS,
    )


def _verify_no_forecast_exists(state):
    rows, meta = validate_paginated(
        api_client.list_demand_forecasts(
            ZONE_ADMIN_HEADERS, params={"zone_id": state["zone"]["id"]}
        )
    )
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


def _attempt_analyst_certifies_own_filing(state):
    return api_client.certify_subsidy_report(
        state["filed_report"]["id"], FINANCE_ANALYST_HEADERS, {"note": "self-certified"}
    )


def _verify_filed_report_untouched(state):
    assertions.assert_report_state(
        fixtures.refresh_report(state["filed_report"]["id"]), "SUBMITTED"
    )


def _attempt_auditor_submits_draft(state):
    return api_client.submit_subsidy_report(
        state["draft_report"]["id"], AUDITOR_HEADERS
    )


def _verify_draft_report_untouched(state):
    assertions.assert_report_state(
        fixtures.refresh_report(state["draft_report"]["id"]), "DRAFT"
    )


def _attempt_driver_closes_block(state):
    return api_client.close_vehicle_block(
        state["block"]["id"], make_driver_headers(state["driver"]["id"])
    )


def _verify_block_untouched(state):
    block = fixtures.refresh_block(state["block"]["id"])
    assertions.assert_block_state(block, "OPEN")
    assertions.assert_version_unchanged(state["block"], block)


CROSSED_ROLE_ATTEMPTS = {
    "dispatcher_approves_a_virtual_stop": (
        _attempt_dispatcher_approves_stop,
        _verify_stop_untouched,
    ),
    "zone_admin_creates_a_pool_assignment": (
        _attempt_zone_admin_creates_offer,
        _verify_no_offer_exists,
    ),
    "dispatcher_publishes_a_demand_forecast": (
        _attempt_dispatcher_publishes_forecast,
        _verify_no_forecast_exists,
    ),
    "finance_analyst_certifies_a_filed_report": (
        _attempt_analyst_certifies_own_filing,
        _verify_filed_report_untouched,
    ),
    "auditor_submits_a_draft_report": (
        _attempt_auditor_submits_draft,
        _verify_draft_report_untouched,
    ),
    "driver_closes_a_vehicle_block": (
        _attempt_driver_closes_block,
        _verify_block_untouched,
    ),
}


@pytest.mark.parametrize("attempt_name", sorted(CROSSED_ROLE_ATTEMPTS))
def test_no_role_reaches_another_roles_exclusive_operation(attempt_name):
    """A recognised role acting outside the called endpoint's authorised set is refused and writes nothing.

    PRD: "If `X-User-Role` is not one of those six strings, or is one of them but is not among the roles authorised for the endpoint being called (see the Authorized Role(s) column in Section 4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/no_role_cannot_reach_another_roles_exclusive_operations
    """
    state = _crossed_role_state()
    attempt, verify_untouched = CROSSED_ROLE_ATTEMPTS[attempt_name]

    validate_error(
        attempt(state), ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403
    )

    verify_untouched(state)


# ─── shared operations accept each of their permitted roles ────────────────


def _shared_surface_state() -> dict:
    """An active zone with two approved stops and one vehicle, driver and rider,
    ready for the operations both operator roles share."""
    fixtures.set_clock("2026-08-03T06:00:00Z", headers=DISPATCHER_HEADERS)
    zone = fixtures.create_active_zone()
    return {
        "zone": zone,
        "origin": fixtures.create_approved_stop(zone["id"], "S0", 0),
        "destination": fixtures.create_approved_stop(zone["id"], "S4", 4),
        "vehicle": fixtures.create_vehicle(zone["id"], "V1"),
        "driver": fixtures.create_driver(zone["id"], "D1"),
        "rider": fixtures.create_rider(zone["id"], "R1"),
    }


def test_block_scheduling_and_driver_status_accept_either_operations_role():
    """A block scheduled by the ZoneAdmin is opened by the Dispatcher, and the driver status capability answers both.

    PRD: "Both `ZoneAdmin` and `Dispatcher` callers may schedule one, supplying the `zone_id` it runs in, the `vehicle_id` pinned to it, the `driver_id` rostered on it, a `block_type` of either `BASE` or `SURGE` declaring whether the block counts against base or peak-surge fleet sizing, and the window itself as an inclusive `start_utc` and an exclusive `end_utc` that must be strictly later than the start."

    Design: Corner/rbac/shared_operations_accept_each_of_their_permitted_roles
    """
    state = _shared_surface_state()

    block = validate_success(
        api_client.create_vehicle_block(
            vehicle_block_payload(
                state["zone"]["id"], state["vehicle"]["id"], state["driver"]["id"]
            ),
            ZONE_ADMIN_HEADERS,
        ),
        201,
    )
    assertions.assert_block_state(block, "SCHEDULED")

    block = validate_success(
        api_client.open_vehicle_block(block["id"], DISPATCHER_HEADERS), 200
    )
    assertions.assert_block_state(block, "OPEN")

    driver = validate_success(
        api_client.set_driver_status(
            state["driver"]["id"], {"status": "SUSPENDED"}, DISPATCHER_HEADERS
        ),
        200,
    )
    assertions.assert_fields(driver, status="SUSPENDED")

    driver = validate_success(
        api_client.set_driver_status(
            state["driver"]["id"], {"status": "ACTIVE"}, ZONE_ADMIN_HEADERS
        ),
        200,
    )
    assertions.assert_fields(driver, status="ACTIVE", consecutive_decline_count=0)

    # Suspension only sweeps SCHEDULED blocks, so the open block survives it.
    assertions.assert_block_state(fixtures.refresh_block(block["id"]), "OPEN")


def test_trip_intake_and_cancellation_accept_the_rider_and_the_dispatcher():
    """A rider files her own trip and the Dispatcher files and cancels another on her behalf.

    PRD: "A **trip request** is created either by the rider themselves or by a `Dispatcher` acting on their behalf, and requires the zone to be `ACTIVE`."

    Design: Corner/rbac/shared_operations_accept_each_of_their_permitted_roles
    """
    state = _shared_surface_state()
    zone_id = state["zone"]["id"]
    rider_id = state["rider"]["id"]

    own_trip = validate_success(
        api_client.create_trip_request(
            trip_request_payload(
                zone_id, rider_id, state["origin"]["id"], state["destination"]["id"]
            ),
            make_rider_headers(rider_id),
        ),
        201,
    )
    assertions.assert_fields(own_trip, rider_id=rider_id)
    assertions.assert_trip_state(own_trip, "RECEIVED", "UNPRICED")

    agent_trip = validate_success(
        api_client.create_trip_request(
            trip_request_payload(
                zone_id,
                rider_id,
                state["origin"]["id"],
                state["destination"]["id"],
                requested_pickup_utc="2026-08-03T08:00:00Z",
            ),
            DISPATCHER_HEADERS,
        ),
        201,
    )
    assertions.assert_fields(agent_trip, rider_id=rider_id)

    cancelled = validate_success(
        api_client.cancel_trip_request(
            agent_trip["id"],
            DISPATCHER_HEADERS,
            {"note": "rider called the call centre"},
        ),
        200,
    )
    assertions.assert_trip_state(cancelled, "CANCELLED")
    assertions.assert_trip_state(fixtures.refresh_trip(own_trip["id"]), "RECEIVED")


def test_shared_read_endpoints_answer_each_authorised_role():
    """The collection reads authorised for all roles answer every one of the six, including the two entity-backed ones.

    PRD: "If `X-User-Role` is not one of those six strings, or is one of them but is not among the roles authorised for the endpoint being called (see the Authorized Role(s) column in Section 4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/shared_operations_accept_each_of_their_permitted_roles
    """
    state = _shared_surface_state()
    zone_id = state["zone"]["id"]
    block = validate_success(
        api_client.create_vehicle_block(
            vehicle_block_payload(zone_id, state["vehicle"]["id"], state["driver"]["id"]),
            ZONE_ADMIN_HEADERS,
        ),
        201,
    )

    every_role = [
        ZONE_ADMIN_HEADERS,
        DISPATCHER_HEADERS,
        FINANCE_ANALYST_HEADERS,
        AUDITOR_HEADERS,
        make_rider_headers(state["rider"]["id"]),
        make_driver_headers(state["driver"]["id"]),
    ]
    for headers in every_role:
        zones, meta = validate_paginated(api_client.list_service_zones(headers))
        assert meta["total_count"] == 1, (headers, meta)
        assertions.assert_contains_ids(zones, zone_id)

    blocks, blocks_meta = validate_paginated(
        api_client.list_vehicle_blocks(
            FINANCE_ANALYST_HEADERS, params={"zone_id": zone_id}
        )
    )
    assert blocks_meta["total_count"] == 1, blocks_meta
    assertions.assert_contains_ids(blocks, block["id"])


# ─── stale-view protection on the two capacity-bearing writes ──────────────


def test_stale_expected_vehicle_block_version_blocks_the_second_offer():
    """Replaying the block version observed at open on a second offer is refused, and retrying with the fresh version succeeds.

    PRD: "If that value does not equal the block's current `version`, the request is rejected with `ERR_STALE_VEHICLE_BLOCK_VERSION` (HTTP 412)."

    Design: Corner/cross-cutting complexity layers/stale_expected_vehicle_block_version_blocks_the_second_offer
    """
    fixtures.set_clock("2026-08-03T06:00:00Z", headers=ZONE_ADMIN_HEADERS)
    zone = fixtures.create_active_zone()
    origin = fixtures.create_approved_stop(zone["id"], "S0", 0)
    destination = fixtures.create_approved_stop(zone["id"], "S4", 4)
    vehicle = fixtures.create_vehicle(zone["id"], "V1")
    driver = fixtures.create_driver(zone["id"], "D1")
    first_rider = fixtures.create_rider(zone["id"], "R1")
    second_rider = fixtures.create_rider(zone["id"], "R2")

    scheduled_block = fixtures.create_block(zone["id"], vehicle["id"], driver["id"])
    block = fixtures.open_block(scheduled_block["id"])
    assertions.assert_version_advanced(scheduled_block, block)
    version_at_open = block["version"]

    first_trip = fixtures.create_trip(
        zone["id"], first_rider["id"], origin["id"], destination["id"]
    )
    second_trip = fixtures.create_trip(
        zone["id"],
        second_rider["id"],
        origin["id"],
        destination["id"],
        requested_pickup_utc="2026-08-03T07:10:00Z",
    )

    # The first offer succeeds on the version observed at open and consumes a seat.
    fixtures.dispatch_trip(
        first_trip["id"], block["id"], expected_version=version_at_open
    )

    # Replaying that same version is now stale.
    validate_error(
        api_client.create_pool_assignment(
            pool_assignment_payload(
                second_trip["id"], block["id"], version_at_open
            ),
            DISPATCHER_HEADERS,
        ),
        ApiErrorId.ERR_STALE_VEHICLE_BLOCK_VERSION.value,
        412,
    )

    # The rejected write consumed nothing.
    block_after_rejection = fixtures.refresh_block(block["id"])
    assertions.assert_block_commitments(
        block_after_rejection,
        seats_committed=1,
        wav_positions_committed=0,
        committed_index_min=0,
        committed_index_max=4,
    )
    rejected_trip = fixtures.refresh_trip(second_trip["id"])
    assertions.assert_trip_state(rejected_trip, "RECEIVED", "UNPRICED")
    assertions.assert_null_fields(rejected_trip, "assigned_block_id")

    fresh_version = block_after_rejection["version"]
    assert fresh_version == version_at_open + 1, (fresh_version, version_at_open)

    retry = validate_success(
        api_client.create_pool_assignment(
            pool_assignment_payload(second_trip["id"], block["id"], fresh_version),
            DISPATCHER_HEADERS,
        ),
        201,
    )
    assertions.assert_assignment_state(retry, "OFFERED")

    block_after_retry = fixtures.refresh_block(block["id"])
    assertions.assert_block_commitments(block_after_retry, seats_committed=2)
    assert block_after_retry["version"] == fresh_version + 1, block_after_retry


def test_stale_expected_service_zone_version_blocks_the_forecast_publish():
    """A forecast published from a zone version invalidated by a suspend and reactivate cycle is refused.

    PRD: "If that value does not equal the zone's current `version`, the request is rejected with `ERR_STALE_SERVICE_ZONE_VERSION` (HTTP 412)."

    Design: Corner/cross-cutting complexity layers/stale_expected_service_zone_version_blocks_the_forecast_publish
    """
    fixtures.set_clock("2026-08-03T05:00:00Z", headers=ZONE_ADMIN_HEADERS)
    zone = fixtures.create_zone()
    activated = fixtures.activate_zone(zone["id"])
    stale_version = activated["version"]

    fixtures.suspend_zone(zone["id"])
    reactivated = fixtures.activate_zone(zone["id"])
    current_version = reactivated["version"]
    assertions.assert_fields(reactivated, status="ACTIVE")
    assert current_version == stale_version + 2, (current_version, stale_version)

    validate_error(
        api_client.create_demand_forecast(
            demand_forecast_payload(zone["id"], stale_version), ZONE_ADMIN_HEADERS
        ),
        ApiErrorId.ERR_STALE_SERVICE_ZONE_VERSION.value,
        412,
    )

    rows, meta = validate_paginated(
        api_client.list_demand_forecasts(
            ZONE_ADMIN_HEADERS, params={"zone_id": zone["id"]}
        )
    )
    assert meta["total_count"] == 0, meta
    assert rows == [], rows
    # The rejection is a version conflict, not a zone-state failure: the zone is
    # ACTIVE throughout and the refused write bumped nothing.
    assertions.assert_fields(
        fixtures.refresh_zone(zone["id"]), status="ACTIVE", version=current_version
    )

    forecast = validate_success(
        api_client.create_demand_forecast(
            demand_forecast_payload(zone["id"], current_version), ZONE_ADMIN_HEADERS
        ),
        201,
    )
    assertions.assert_fields(forecast, state="PUBLISHED")

    assertions.assert_fields(
        fixtures.refresh_zone(zone["id"]),
        status="ACTIVE",
        version=current_version + 1,
    )


# ─── cascades settle inside the request that caused them ───────────────────


def test_cancel_cascade_is_visible_in_its_own_response_and_on_immediate_reread():
    """Cancelling an offered trip shows the cleared trip in its own response and the released offer and returned capacity on the very next read.

    PRD: "When an operation's cascade recomputes a derived field — a block's committed seat count, a zone's average wait, a rider's daily fare counter — that recomputation happens inside the same request, and the very next read observes the settled values."

    Design: Corner/consistency model/cascade_results_are_visible_in_the_same_response_and_on_immediate_reread
    """
    fixtures.set_clock("2026-08-03T06:00:00Z", headers=ZONE_ADMIN_HEADERS)
    zone = fixtures.create_active_zone()
    origin = fixtures.create_approved_stop(zone["id"], "S0", 0)
    destination = fixtures.create_approved_stop(zone["id"], "S4", 4)
    vehicle = fixtures.create_vehicle(zone["id"], "V1")
    driver = fixtures.create_driver(zone["id"], "D1")
    rider = fixtures.create_rider(zone["id"], "R1", mobility_device="WHEELCHAIR")
    block = fixtures.open_block(
        fixtures.create_block(zone["id"], vehicle["id"], driver["id"])["id"]
    )
    trip = fixtures.create_trip(
        zone["id"],
        rider["id"],
        origin["id"],
        destination["id"],
        party_size=2,
    )
    assignment = fixtures.dispatch_trip(
        trip["id"], block["id"], expected_version=block["version"]
    )

    offered_block = fixtures.refresh_block(block["id"])
    assertions.assert_block_commitments(
        offered_block,
        seats_committed=2,
        wav_positions_committed=1,
        committed_index_min=0,
        committed_index_max=4,
    )
    offered_trip = fixtures.refresh_trip(trip["id"])
    assertions.assert_trip_state(offered_trip, "OFFERED", "QUOTED")
    # A wheelchair declaration forces accessible handling, and a twelve-minute
    # direct ride quotes 250 + 75 cents for a FULL rider.
    assertions.assert_fields(
        offered_trip, wav_required=True, quoted_fare_cents=325, party_size=2
    )

    cancelled = validate_success(
        api_client.cancel_trip_request(
            trip["id"],
            make_rider_headers(rider["id"]),
            {"note": "rider no longer needs the ride"},
        ),
        200,
    )
    # The cancel response itself already carries the settled fulfilment and fare axes.
    assertions.assert_trip_state(cancelled, "CANCELLED", "UNPRICED")
    assertions.assert_null_fields(
        cancelled,
        "assigned_block_id",
        "quoted_fare_cents",
        "promised_pickup_utc",
        "promised_dropoff_utc",
        "projected_detour_minutes",
    )

    assertions.assert_assignment_state(
        fixtures.refresh_assignment(assignment["id"]), "RELEASED"
    )
    released_block = fixtures.refresh_block(block["id"])
    assertions.assert_block_commitments(
        released_block,
        seats_committed=0,
        wav_positions_committed=0,
        committed_index_min=None,
        committed_index_max=None,
    )
    assertions.assert_version_advanced(offered_block, released_block)

    ledger, ledger_meta = validate_paginated(
        api_client.list_fare_transactions(
            DISPATCHER_HEADERS, params={"trip_request_id": trip["id"]}
        )
    )
    assert ledger_meta["total_count"] == 0, ledger_meta
    assert ledger == [], ledger
