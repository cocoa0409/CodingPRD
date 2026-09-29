"""State builders and pytest fixtures.

The server is relaunched with an empty database before every individual test, so
every builder here composes its state from scratch through the public endpoints
only. Builders are plain callables (so a test can call them twice, or with
overrides, inside one test body); the pytest fixtures at the bottom of the file
wrap the most frequently reused compositions.

Layering, cheapest first:
  * clock and single-row builders          -> set_clock, create_zone, create_stop, ...
  * corridor / roster bundles              -> build_corridor, build_roster
  * dispatch-ready service state           -> setup_dispatch_ready
  * live trip progressions                 -> setup_offered_trip .. setup_completed_trip
  * accumulation and finalisation targets  -> setup_rider_at_daily_cap,
                                              setup_closed_block, setup_submitted_report,
                                              setup_certified_report
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    clock_payload,
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
from .test_users import (
    AUDITOR_HEADERS,
    DISPATCHER_HEADERS,
    FINANCE_ANALYST_HEADERS,
    ZONE_ADMIN_HEADERS,
    make_driver_headers,
    make_rider_headers,
)

# ─── Logical clock ─────────────────────────────────────────────────────────


def set_clock(instant: str, headers=None) -> dict:
    """Move the server's logical clock to `instant`."""
    return get_success_data(
        api_client.set_current_utc(
            clock_payload(instant), headers or DISPATCHER_HEADERS
        )
    )


# ─── Service zone ──────────────────────────────────────────────────────────


def create_zone(headers=None, **overrides) -> dict:
    """A zone in DRAFT."""
    return get_success_data(
        api_client.create_service_zone(
            service_zone_payload(**overrides), headers or ZONE_ADMIN_HEADERS
        ),
        expected_status=201,
    )


def activate_zone(zone_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.activate_service_zone(zone_id, headers or ZONE_ADMIN_HEADERS)
    )


def suspend_zone(zone_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.suspend_service_zone(zone_id, headers or ZONE_ADMIN_HEADERS)
    )


def create_active_zone(headers=None, **overrides) -> dict:
    """A zone already moved to ACTIVE, so intake and dispatch are open."""
    zone = create_zone(headers=headers, **overrides)
    return activate_zone(zone["id"], headers=headers)


def refresh_zone(zone_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_service_zone(zone_id, headers or ZONE_ADMIN_HEADERS)
    )


# ─── Virtual stops and the corridor ────────────────────────────────────────


def create_stop(
    zone_id: str, stop_code: str, corridor_index: int, headers=None, **overrides
) -> dict:
    """A stop in PROPOSED."""
    return get_success_data(
        api_client.create_virtual_stop(
            virtual_stop_payload(zone_id, stop_code, corridor_index, **overrides),
            headers or ZONE_ADMIN_HEADERS,
        ),
        expected_status=201,
    )


def approve_stop(stop_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.approve_virtual_stop(stop_id, headers or ZONE_ADMIN_HEADERS)
    )


def retire_stop(stop_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.retire_virtual_stop(stop_id, headers or ZONE_ADMIN_HEADERS)
    )


def create_approved_stop(
    zone_id: str, stop_code: str, corridor_index: int, headers=None, **overrides
) -> dict:
    """A stop approved for revenue use, ready to carry trips."""
    stop = create_stop(
        zone_id, stop_code, corridor_index, headers=headers, **overrides
    )
    return approve_stop(stop["id"], headers=headers)


def build_corridor(zone_id: str, indexes=(0, 2, 4, 5, 6, 7, 10), headers=None) -> dict:
    """Approve one stop per corridor index and return them keyed by index.

    One index step is three minutes of running time, so index arithmetic fixes
    every baseline direct ride these tests rely on: 0 -> 4 is twelve minutes,
    0 -> 7 is twenty-one minutes.
    """
    stops = {}
    for index in indexes:
        stops[index] = create_approved_stop(
            zone_id, f"S{index}", index, headers=headers
        )
    return stops


def refresh_stop(stop_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_virtual_stop(stop_id, headers or ZONE_ADMIN_HEADERS)
    )


# ─── Transit connections ───────────────────────────────────────────────────


def create_connection(zone_id: str, stop_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_transit_connection(
            transit_connection_payload(zone_id, stop_id, **overrides),
            headers or ZONE_ADMIN_HEADERS,
        ),
        expected_status=201,
    )


def refresh_connection(connection_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_transit_connection(connection_id, headers or ZONE_ADMIN_HEADERS)
    )


# ─── Fleet, drivers, riders ────────────────────────────────────────────────


def create_vehicle(zone_id: str, vehicle_code="V1", headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_vehicle(
            vehicle_payload(zone_id, vehicle_code, **overrides),
            headers or ZONE_ADMIN_HEADERS,
        ),
        expected_status=201,
    )


def set_vehicle_status(vehicle_id: str, status: str, headers=None) -> dict:
    return get_success_data(
        api_client.set_vehicle_status(
            vehicle_id, {"status": status}, headers or ZONE_ADMIN_HEADERS
        )
    )


def refresh_vehicle(vehicle_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_vehicle(vehicle_id, headers or ZONE_ADMIN_HEADERS)
    )


def create_driver(zone_id: str, driver_code="D1", headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_driver(
            driver_payload(zone_id, driver_code, **overrides),
            headers or ZONE_ADMIN_HEADERS,
        ),
        expected_status=201,
    )


def set_driver_status(driver_id: str, status: str, headers=None) -> dict:
    return get_success_data(
        api_client.set_driver_status(
            driver_id, {"status": status}, headers or ZONE_ADMIN_HEADERS
        )
    )


def refresh_driver(driver_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_driver(driver_id, headers or ZONE_ADMIN_HEADERS)
    )


def create_rider(zone_id: str, rider_code="R1", headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_rider(
            rider_payload(zone_id, rider_code, **overrides),
            headers or ZONE_ADMIN_HEADERS,
        ),
        expected_status=201,
    )


def refresh_rider(rider_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_rider(rider_id, headers or ZONE_ADMIN_HEADERS)
    )


def build_roster(
    zone_id: str,
    vehicle_codes=("V1",),
    driver_codes=("D1",),
    rider_codes=("R1",),
    headers=None,
) -> dict:
    """Create the fleet, driver and rider rows a dispatch scenario needs."""
    return {
        "vehicles": {
            code: create_vehicle(zone_id, code, headers=headers)
            for code in vehicle_codes
        },
        "drivers": {
            code: create_driver(zone_id, code, headers=headers)
            for code in driver_codes
        },
        "riders": {
            code: create_rider(zone_id, code, headers=headers) for code in rider_codes
        },
    }


# ─── Demand forecasts ──────────────────────────────────────────────────────


def create_forecast(zone_id: str, zone_version=None, headers=None, **overrides) -> dict:
    """Publish a forecast. The zone version is read live unless pinned."""
    if zone_version is None:
        zone_version = refresh_zone(zone_id)["version"]
    return get_success_data(
        api_client.create_demand_forecast(
            demand_forecast_payload(zone_id, zone_version, **overrides),
            headers or ZONE_ADMIN_HEADERS,
        ),
        expected_status=201,
    )


def refresh_forecast(forecast_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_demand_forecast(forecast_id, headers or ZONE_ADMIN_HEADERS)
    )


# ─── Vehicle blocks ────────────────────────────────────────────────────────


def create_block(
    zone_id: str, vehicle_id: str, driver_id: str, headers=None, **overrides
) -> dict:
    """A block in SCHEDULED."""
    return get_success_data(
        api_client.create_vehicle_block(
            vehicle_block_payload(zone_id, vehicle_id, driver_id, **overrides),
            headers or DISPATCHER_HEADERS,
        ),
        expected_status=201,
    )


def open_block(block_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.open_vehicle_block(block_id, headers or DISPATCHER_HEADERS)
    )


def close_block(block_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.close_vehicle_block(block_id, headers or DISPATCHER_HEADERS)
    )


def cancel_block(block_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.cancel_vehicle_block(block_id, headers or DISPATCHER_HEADERS)
    )


def create_open_block(
    zone_id: str, vehicle_id: str, driver_id: str, headers=None, **overrides
) -> dict:
    """A block pulled out for service, ready to receive offers."""
    block = create_block(zone_id, vehicle_id, driver_id, headers=headers, **overrides)
    return open_block(block["id"], headers=headers)


def refresh_block(block_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_vehicle_block(block_id, headers or DISPATCHER_HEADERS)
    )


def block_version(block_id: str, headers=None) -> int:
    return refresh_block(block_id, headers=headers)["version"]


# ─── Trip requests ─────────────────────────────────────────────────────────


def create_trip(
    zone_id: str,
    rider_id: str,
    origin_stop_id: str,
    destination_stop_id: str,
    headers=None,
    **overrides,
) -> dict:
    """A trip in RECEIVED / UNPRICED, intaken by its own rider by default."""
    return get_success_data(
        api_client.create_trip_request(
            trip_request_payload(
                zone_id, rider_id, origin_stop_id, destination_stop_id, **overrides
            ),
            headers or make_rider_headers(rider_id),
        ),
        expected_status=201,
    )


def match_trip(trip_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.match_trip_request(trip_id, headers or DISPATCHER_HEADERS)
    )


def cancel_trip(trip_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.cancel_trip_request(trip_id, headers or DISPATCHER_HEADERS)
    )


def refund_trip(trip_id: str, reason="service failure", headers=None) -> dict:
    return get_success_data(
        api_client.refund_trip_request(
            trip_id, {"reason": reason}, headers or DISPATCHER_HEADERS
        )
    )


def refresh_trip(trip_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_trip_request(trip_id, headers or DISPATCHER_HEADERS)
    )


def list_trips(params=None, headers=None) -> list:
    data = get_success_data(
        api_client.list_trip_requests(headers or DISPATCHER_HEADERS, params=params)
    )
    return data["data"] if isinstance(data, dict) and "data" in data else data


# ─── Pool assignments ──────────────────────────────────────────────────────


def dispatch_trip(
    trip_id: str, block_id: str, expected_version=None, headers=None, **overrides
) -> dict:
    """Manually dispatch a trip onto a block; the block version is read live
    unless the caller pins one to exercise the concurrency check."""
    if expected_version is None:
        expected_version = block_version(block_id)
    return get_success_data(
        api_client.create_pool_assignment(
            pool_assignment_payload(trip_id, block_id, expected_version, **overrides),
            headers or DISPATCHER_HEADERS,
        ),
        expected_status=201,
    )


def accept_assignment(assignment_id: str, driver_id: str) -> dict:
    return get_success_data(
        api_client.accept_pool_assignment(
            assignment_id, make_driver_headers(driver_id)
        )
    )


def decline_assignment(assignment_id: str, driver_id: str) -> dict:
    return get_success_data(
        api_client.decline_pool_assignment(
            assignment_id, make_driver_headers(driver_id)
        )
    )


def board_assignment(assignment_id: str, driver_id: str) -> dict:
    return get_success_data(
        api_client.board_pool_assignment(assignment_id, make_driver_headers(driver_id))
    )


def complete_assignment(assignment_id: str, driver_id: str) -> dict:
    return get_success_data(
        api_client.complete_pool_assignment(
            assignment_id, make_driver_headers(driver_id)
        )
    )


def refresh_assignment(assignment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_pool_assignment(assignment_id, headers or DISPATCHER_HEADERS)
    )


def list_assignments(params=None, headers=None) -> list:
    data = get_success_data(
        api_client.list_pool_assignments(headers or DISPATCHER_HEADERS, params=params)
    )
    return data["data"] if isinstance(data, dict) and "data" in data else data


def assignments_for_trip(trip_id: str, headers=None) -> list:
    return list_assignments({"trip_request_id": trip_id}, headers=headers)


def live_assignment_for_trip(trip_id: str, headers=None) -> dict:
    """The one assignment the matcher or the dispatcher just created."""
    rows = assignments_for_trip(trip_id, headers=headers)
    assert rows, f"no pool assignment exists for trip {trip_id}"
    return rows[-1]


# ─── Fare ledger ───────────────────────────────────────────────────────────


def list_fare_transactions(params=None, headers=None) -> list:
    data = get_success_data(
        api_client.list_fare_transactions(headers or DISPATCHER_HEADERS, params=params)
    )
    return data["data"] if isinstance(data, dict) and "data" in data else data


def ledger_for_trip(trip_id: str, headers=None) -> list:
    return list_fare_transactions({"trip_request_id": trip_id}, headers=headers)


def ledger_for_rider(rider_id: str, headers=None) -> list:
    return list_fare_transactions({"rider_id": rider_id}, headers=headers)


# ─── Subsidy reports ───────────────────────────────────────────────────────


def create_report(zone_id: str, headers=None, **overrides) -> dict:
    """A report in DRAFT with all four totals already computed."""
    return get_success_data(
        api_client.create_subsidy_report(
            subsidy_report_payload(zone_id, **overrides),
            headers or FINANCE_ANALYST_HEADERS,
        ),
        expected_status=201,
    )


def submit_report(report_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.submit_subsidy_report(report_id, headers or FINANCE_ANALYST_HEADERS)
    )


def certify_report(report_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.certify_subsidy_report(report_id, headers or AUDITOR_HEADERS)
    )


def reject_report(report_id: str, reason="totals disputed", headers=None) -> dict:
    return get_success_data(
        api_client.reject_subsidy_report(
            report_id, {"rejection_reason": reason}, headers or AUDITOR_HEADERS
        )
    )


def amend_report(report_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.amend_subsidy_report(report_id, headers or FINANCE_ANALYST_HEADERS)
    )


def refresh_report(report_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_subsidy_report(report_id, headers or FINANCE_ANALYST_HEADERS)
    )


# ─── Composite: dispatch-ready service ─────────────────────────────────────

DEFAULT_CORRIDOR = (0, 2, 4, 5, 6, 7, 10)


def setup_dispatch_ready(
    zone_overrides=None,
    corridor=DEFAULT_CORRIDOR,
    vehicle_overrides=None,
    driver_overrides=None,
    rider_overrides=None,
    block_overrides=None,
    clock_at=None,
    open_the_block=True,
) -> dict:
    """Active zone, approved corridor, one vehicle, one driver, one rider and a
    block over 06:00Z-10:00Z on the service day, opened by default.

    Returns a flat bag: zone, stops (by corridor index), vehicle, driver, rider,
    block, plus the headers the block's driver and the rider must use.
    """
    set_clock(clock_at or TEST_DEFAULTS["BLOCK_START_UTC"])
    zone = create_active_zone(**(zone_overrides or {}))
    stops = build_corridor(zone["id"], indexes=corridor)
    # A caller may override the operator-assigned code itself, so the code is
    # lifted out of the override bag rather than passed positionally twice.
    vehicle_overrides = dict(vehicle_overrides or {})
    driver_overrides = dict(driver_overrides or {})
    rider_overrides = dict(rider_overrides or {})
    vehicle = create_vehicle(
        zone["id"], vehicle_overrides.pop("vehicle_code", "V1"), **vehicle_overrides
    )
    driver = create_driver(
        zone["id"], driver_overrides.pop("driver_code", "D1"), **driver_overrides
    )
    rider = create_rider(
        zone["id"], rider_overrides.pop("rider_code", "R1"), **rider_overrides
    )
    block = create_block(
        zone["id"], vehicle["id"], driver["id"], **(block_overrides or {})
    )
    if open_the_block:
        block = open_block(block["id"])
    return {
        "zone": zone,
        "stops": stops,
        "vehicle": vehicle,
        "driver": driver,
        "rider": rider,
        "block": block,
        "driver_headers": make_driver_headers(driver["id"]),
        "rider_headers": make_rider_headers(rider["id"]),
    }


def setup_capped_zone_ready(**kwargs) -> dict:
    """Dispatch-ready state whose daily fare cap is 300 cents, low enough that a
    single 325-cent quote is trimmed by the cap on settlement."""
    zone_overrides = {
        "zone_code": "RBM-CAP",
        "fare_cap_cents_daily": 300,
    }
    zone_overrides.update(kwargs.pop("zone_overrides", None) or {})
    return setup_dispatch_ready(zone_overrides=zone_overrides, **kwargs)


def setup_roomy_curb_ready(**kwargs) -> dict:
    """Dispatch-ready state whose curb capacity is six per bucket, so curb
    congestion never masks the check under test."""
    zone_overrides = {"zone_code": "RBM-DTR", "curb_capacity_per_bucket": 6}
    zone_overrides.update(kwargs.pop("zone_overrides", None) or {})
    return setup_dispatch_ready(zone_overrides=zone_overrides, **kwargs)


# ─── Composite: live trip progressions ─────────────────────────────────────


def setup_received_trip(state=None, origin_index=0, destination_index=4, **overrides):
    """Dispatch-ready state plus one trip in RECEIVED / UNPRICED."""
    state = state or setup_dispatch_ready()
    trip = create_trip(
        state["zone"]["id"],
        state["rider"]["id"],
        state["stops"][origin_index]["id"],
        state["stops"][destination_index]["id"],
        **overrides,
    )
    state["trip"] = trip
    return state


def setup_offered_trip(
    state=None, origin_index=0, destination_index=4, manual=False, **overrides
):
    """A trip offered onto the open block, either by running matching or by
    manual dispatch, with its assignment resolved."""
    state = setup_received_trip(
        state=state,
        origin_index=origin_index,
        destination_index=destination_index,
        **overrides,
    )
    if manual:
        state["assignment"] = dispatch_trip(
            state["trip"]["id"], state["block"]["id"]
        )
    else:
        match_trip(state["trip"]["id"])
        state["assignment"] = live_assignment_for_trip(state["trip"]["id"])
    state["trip"] = refresh_trip(state["trip"]["id"])
    state["block"] = refresh_block(state["block"]["id"])
    return state


def setup_accepted_trip(state=None, **kwargs):
    """The block's driver has accepted the offer, so the trip is ASSIGNED."""
    state = setup_offered_trip(state=state, **kwargs)
    state["assignment"] = accept_assignment(
        state["assignment"]["id"], state["driver"]["id"]
    )
    state["trip"] = refresh_trip(state["trip"]["id"])
    state["block"] = refresh_block(state["block"]["id"])
    return state


def setup_onboard_trip(state=None, board_at=None, **kwargs):
    """The rider is aboard: the assignment is ONBOARD and the trip PICKED_UP."""
    state = setup_accepted_trip(state=state, **kwargs)
    if board_at:
        set_clock(board_at)
    state["assignment"] = board_assignment(
        state["assignment"]["id"], state["driver"]["id"]
    )
    state["trip"] = refresh_trip(state["trip"]["id"])
    return state


def setup_completed_trip(state=None, board_at=None, complete_at=None, **kwargs):
    """The ride is finished, the fare settled and the ledger written."""
    state = setup_onboard_trip(state=state, board_at=board_at, **kwargs)
    if complete_at:
        set_clock(complete_at)
    state["assignment"] = complete_assignment(
        state["assignment"]["id"], state["driver"]["id"]
    )
    state["trip"] = refresh_trip(state["trip"]["id"])
    state["block"] = refresh_block(state["block"]["id"])
    state["zone"] = refresh_zone(state["zone"]["id"])
    state["ledger"] = ledger_for_trip(state["trip"]["id"])
    return state


def run_trip_to_completion(
    state,
    rider_id=None,
    origin_index=0,
    destination_index=4,
    board_at=None,
    complete_at=None,
    **overrides,
):
    """Drive one extra trip on an existing block from intake to completion and
    return that trip. Used to accumulate fare counters and zone metrics."""
    rider_id = rider_id or state["rider"]["id"]
    trip = create_trip(
        state["zone"]["id"],
        rider_id,
        state["stops"][origin_index]["id"],
        state["stops"][destination_index]["id"],
        **overrides,
    )
    match_trip(trip["id"])
    assignment = live_assignment_for_trip(trip["id"])
    accept_assignment(assignment["id"], state["driver"]["id"])
    if board_at:
        set_clock(board_at)
    board_assignment(assignment["id"], state["driver"]["id"])
    if complete_at:
        set_clock(complete_at)
    complete_assignment(assignment["id"], state["driver"]["id"])
    return refresh_trip(trip["id"])


# ─── Composite: accumulation targets ───────────────────────────────────────


def setup_rider_at_daily_cap(**kwargs) -> dict:
    """A rider on the 300-cent-daily-cap zone who has already settled one
    325-cent ride, so the day's cap is fully consumed."""
    state = setup_completed_trip(state=setup_capped_zone_ready(**kwargs))
    state["rider"] = refresh_rider(state["rider"]["id"])
    return state


def setup_declining_driver(state=None, declines=1, **kwargs) -> dict:
    """A driver carrying a decline streak of `declines`, built by offering and
    declining that many trips on their own block."""
    state = state or setup_dispatch_ready()
    for n in range(declines):
        rider = create_rider(state["zone"]["id"], f"RD{n}")
        trip = create_trip(
            state["zone"]["id"],
            rider["id"],
            state["stops"][0]["id"],
            state["stops"][4]["id"],
        )
        assignment = dispatch_trip(trip["id"], state["block"]["id"])
        decline_assignment(assignment["id"], state["driver"]["id"])
    state["driver"] = refresh_driver(state["driver"]["id"])
    return state


# ─── Composite: finalisation targets ───────────────────────────────────────


def setup_closed_block(
    zone_overrides=None,
    opened_at="2026-08-03T06:00:00Z",
    closed_at="2026-08-03T08:00:00Z",
    block_overrides=None,
) -> dict:
    """An active zone with one block opened and closed on the service day and no
    trips at all, so the block's actual revenue hours are the only input to a
    report's operating cost."""
    set_clock(opened_at)
    zone = create_active_zone(**(zone_overrides or {}))
    vehicle = create_vehicle(zone["id"], "V1")
    driver = create_driver(zone["id"], "D1")
    block = create_block(
        zone["id"], vehicle["id"], driver["id"], **(block_overrides or {})
    )
    block = open_block(block["id"])
    set_clock(closed_at)
    block = close_block(block["id"])
    return {
        "zone": zone,
        "vehicle": vehicle,
        "driver": driver,
        "block": block,
    }


def setup_draft_report(state=None, report_overrides=None, **kwargs) -> dict:
    """A DRAFT report over a closed service day."""
    state = state or setup_closed_block(**kwargs)
    state["report"] = create_report(state["zone"]["id"], **(report_overrides or {}))
    return state


def setup_submitted_report(state=None, **kwargs) -> dict:
    state = setup_draft_report(state=state, **kwargs)
    state["report"] = submit_report(state["report"]["id"])
    return state


def setup_certified_report(state=None, **kwargs) -> dict:
    """A report filed by the analyst and certified by the auditor, i.e. the only
    state from which an amendment is legal."""
    state = setup_submitted_report(state=state, **kwargs)
    state["report"] = certify_report(state["report"]["id"])
    return state


# ─── Composite: multi-block scenarios ──────────────────────────────────────


def setup_two_open_blocks(
    zone_overrides=None,
    corridor=DEFAULT_CORRIDOR,
    vehicle_a_overrides=None,
    vehicle_b_overrides=None,
    block_overrides=None,
    clock_at=None,
) -> dict:
    """Two distinct vehicle-and-driver blocks open over the same window, so the
    matcher has to choose between candidates."""
    set_clock(clock_at or TEST_DEFAULTS["BLOCK_START_UTC"])
    zone = create_active_zone(**(zone_overrides or {}))
    stops = build_corridor(zone["id"], indexes=corridor)
    vehicle_a = create_vehicle(zone["id"], "VA", **(vehicle_a_overrides or {}))
    vehicle_b = create_vehicle(zone["id"], "VB", **(vehicle_b_overrides or {}))
    driver_a = create_driver(zone["id"], "DA")
    driver_b = create_driver(zone["id"], "DB")
    rider = create_rider(zone["id"], "R1")
    block_a = open_block(
        create_block(
            zone["id"], vehicle_a["id"], driver_a["id"], **(block_overrides or {})
        )["id"]
    )
    block_b = open_block(
        create_block(
            zone["id"], vehicle_b["id"], driver_b["id"], **(block_overrides or {})
        )["id"]
    )
    return {
        "zone": zone,
        "stops": stops,
        "vehicle_a": vehicle_a,
        "vehicle_b": vehicle_b,
        "driver_a": driver_a,
        "driver_b": driver_b,
        "rider": rider,
        "block_a": block_a,
        "block_b": block_b,
    }


def setup_scheduling_sandbox(
    zone_overrides=None, vehicle_codes=("V1", "V2", "V3", "V4"),
    driver_codes=("D1", "D2", "D3", "D4"),
) -> dict:
    """An active zone with several free vehicles and drivers, ready for block
    scheduling tests that probe occupation and the rest buffer."""
    set_clock(TEST_DEFAULTS["BLOCK_START_UTC"])
    zone = create_active_zone(**(zone_overrides or {}))
    roster = build_roster(
        zone["id"],
        vehicle_codes=vehicle_codes,
        driver_codes=driver_codes,
        rider_codes=(),
    )
    return {"zone": zone, **roster}


# ─── pytest fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def clock():
    """The logical clock parked at the start of the service day."""
    return set_clock(TEST_DEFAULTS["BLOCK_START_UTC"])


@pytest.fixture
def draft_zone():
    return create_zone()


@pytest.fixture
def active_zone():
    return create_active_zone()


@pytest.fixture
def zone_with_corridor():
    zone = create_active_zone()
    return {"zone": zone, "stops": build_corridor(zone["id"])}


@pytest.fixture
def dispatch_ready():
    return setup_dispatch_ready()


@pytest.fixture
def capped_zone_ready():
    return setup_capped_zone_ready()


@pytest.fixture
def roomy_curb_ready():
    return setup_roomy_curb_ready()


@pytest.fixture
def received_trip():
    return setup_received_trip()


@pytest.fixture
def offered_trip():
    return setup_offered_trip()


@pytest.fixture
def accepted_trip():
    return setup_accepted_trip()


@pytest.fixture
def onboard_trip():
    return setup_onboard_trip()


@pytest.fixture
def completed_trip():
    return setup_completed_trip()


@pytest.fixture
def two_open_blocks():
    return setup_two_open_blocks()


@pytest.fixture
def scheduling_sandbox():
    return setup_scheduling_sandbox()


@pytest.fixture
def closed_block():
    return setup_closed_block()


@pytest.fixture
def draft_report():
    return setup_draft_report()


@pytest.fixture
def submitted_report():
    return setup_submitted_report()


@pytest.fixture
def certified_report():
    return setup_certified_report()
