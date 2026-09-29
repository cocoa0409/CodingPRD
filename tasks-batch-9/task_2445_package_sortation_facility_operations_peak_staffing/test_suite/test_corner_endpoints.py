"""Endpoint-surface corner cases for the Package Sortation Peak Staffing API.

Every test in this module builds its own world from scratch through the
documented endpoints, because the harness restarts the API server (and empties
the database) before each individual test.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ERR_FACILITY_RESOURCE_NOT_FOUND
from test_helpers.assertions import assert_package_conservation
from test_helpers.test_users import (
    FACILITY_ADMIN_HEADERS,
    OPS_MANAGER_HEADERS,
    SORT_SUPERVISOR_HEADERS,
)


# ─── Local read helpers ───────────────────────────────
# Reads go through the client's documented raw request channel so the caller's
# headers travel as headers.

def _read(api, path, headers, params=None):
    """GET one resource and return its `data` payload."""
    return validate_success(api.request("GET", path, headers=headers, params=params))


def _center(api, center_id, headers=None):
    return _read(
        api, f"/sortation/sort-centers/{center_id}", headers or FACILITY_ADMIN_HEADERS
    )


def _chute(api, chute_id):
    return _read(api, f"/sortation/sort-chutes/{chute_id}", FACILITY_ADMIN_HEADERS)


def _lane(api, lane_id, headers=None):
    return _read(
        api, f"/sortation/destination-lanes/{lane_id}", headers or FACILITY_ADMIN_HEADERS
    )


def _all_lanes(api, center_id):
    rows, _ = validate_paginated(
        api.request(
            "GET",
            f"/sortation/sort-centers/{center_id}/destination-lanes",
            headers=FACILITY_ADMIN_HEADERS,
            params={"limit": 100},
        )
    )
    return rows


def _commission_facility(world, map_assignment=True, forecast_hourly_volume=100):
    """One center at automation 70 with an inbound and an outbound door, one
    chute rated 1,200 packages per hour and one destination lane, optionally
    already mapped onto the chute."""
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    inbound_door = world.create_door(center["id"], door_number=1, kind="INBOUND")
    outbound_door = world.create_door(center["id"], door_number=2, kind="OUTBOUND")
    chute = world.create_chute(center["id"], chute_number=1, throughput_pph=1200)
    lane = world.create_lane(
        center["id"], forecast_hourly_volume=forecast_hourly_volume
    )
    assignment = None
    if map_assignment:
        assignment = world.map_lane_to_chute(
            chute["id"], lane["id"], expected_chute_version=chute["version"]
        )
    return {
        "center": center,
        "inbound_door": inbound_door,
        "outbound_door": outbound_door,
        "chute": chute,
        "lane": lane,
        "assignment": assignment,
    }


# ─── Tests ────────────────────────────────────────────

def test_lane_patch_restates_forecast_then_closes_the_lane(api, world):
    """PRD §3.1: "An admin may later close or reopen a lane (moving `status` between `ACTIVE` and `CLOSED`) or restate `forecast_hourly_volume`; either change recomputes the lane's pressure ratio, bumps its `version`, and recomputes the center's posture, because a lane leaving `ACTIVE` also leaves the population from which the center's peak lane pressure is taken."

    Design: Corner/endpoints/destination_lane_patch_updates_forecast_then_closes_lane
    """
    built = _commission_facility(world, forecast_hourly_volume=3000)
    center_id = built["center"]["id"]
    lane_id = built["lane"]["id"]

    before = _lane(api, lane_id)

    restated = validate_success(
        api.patch_destination_lane(
            lane_id, {"forecast_hourly_volume": 4500}, FACILITY_ADMIN_HEADERS
        )
    )
    assert restated["forecast_hourly_volume"] == 4500
    assert restated["status"] == "ACTIVE", (
        "restating the forecast alone must leave the lane's status alone"
    )

    closed = validate_success(
        api.patch_destination_lane(lane_id, {"status": "CLOSED"}, FACILITY_ADMIN_HEADERS)
    )
    assert closed["status"] == "CLOSED"
    assert closed["forecast_hourly_volume"] == 4500, (
        "closing the lane must leave the restated forecast alone"
    )

    read_back = _lane(api, lane_id, SORT_SUPERVISOR_HEADERS)
    assert read_back["forecast_hourly_volume"] == 4500
    assert read_back["status"] == "CLOSED"
    assert read_back["assigned_capacity_pph"] == 1200
    assert float(read_back["lane_pressure_ratio"]) == 0.0
    assert read_back["backlog_package_count"] == 0
    assert read_back["version"] == before["version"] + 2, (
        "each of the two writes bumps the lane's version by exactly one"
    )

    center = _center(api, center_id)
    assert center["ops_posture"] == "OPEN"


def test_chute_assignment_with_unknown_lane_is_not_found(api, world):
    """PRD §3.2: "A referenced chute, lane or assignment that does not exist yields `ERR_FACILITY_RESOURCE_NOT_FOUND`."

    Design: Corner/endpoints/chute_assignment_link_requires_both_endpoints_to_exist
    """
    built = _commission_facility(world, map_assignment=False, forecast_hourly_volume=3000)
    chute = built["chute"]
    lane = built["lane"]
    pinned_version = chute["version"]

    refused = api.create_chute_assignment(
        f.chute_assignment_payload(chute["id"], NON_EXISTENT_UUID, pinned_version),
        SORT_SUPERVISOR_HEADERS,
    )
    validate_error(refused, ERR_FACILITY_RESOURCE_NOT_FOUND)
    assert _chute(api, chute["id"])["version"] == pinned_version, (
        "the refused create must not have advanced the chute's version"
    )

    created = validate_success(
        api.create_chute_assignment(
            f.chute_assignment_payload(chute["id"], lane["id"], pinned_version),
            SORT_SUPERVISOR_HEADERS,
        ),
        201,
    )
    assert created["status"] == "ACTIVE"
    assert created["chute_id"] == chute["id"]
    assert created["destination_lane_id"] == lane["id"]

    by_chute, chute_meta = validate_paginated(
        api.request(
            "GET",
            "/sortation/chute-assignments",
            headers=SORT_SUPERVISOR_HEADERS,
            params={"chute_id": chute["id"]},
        )
    )
    assert chute_meta["total_count"] == 1
    assert [row["id"] for row in by_chute] == [created["id"]]

    by_lane, lane_meta = validate_paginated(
        api.request(
            "GET",
            "/sortation/chute-assignments",
            headers=SORT_SUPERVISOR_HEADERS,
            params={"destination_lane_id": lane["id"]},
        )
    )
    assert lane_meta["total_count"] == 1
    assert [row["id"] for row in by_lane] == [created["id"]]

    assert _lane(api, lane["id"])["assigned_capacity_pph"] == 1200
    assert _chute(api, chute["id"])["version"] == pinned_version + 1


def test_center_read_matches_the_package_conservation_ledger(api, world):
    """PRD §2.8: "After every request that moves packages, the center's `packages_inducted_count` must equal the sum of its `wip_package_count`, its `exception_hold_count`, its `disposed_package_count`, and the total `sorted_package_count` across *all* destination lanes of that center regardless of lane status (a closed lane still holds the packages already sorted into it)."

    Design: Corner/endpoints/sort_center_computed_read_matches_package_ledger
    """
    built = _commission_facility(world, forecast_hourly_volume=3000)
    center_id = built["center"]["id"]
    lane_id = built["lane"]["id"]

    world.induct_packages(center_id, built["inbound_door"]["id"], 500)
    load = world.stage_load(center_id, built["outbound_door"]["id"], lane_id)
    world.scan(load["id"], small_count=100)
    world.create_exception(
        center_id,
        exception_type="MISSORT",
        package_count=50,
        from_destination_lane_id=lane_id,
    )

    center = _center(api, center_id, OPS_MANAGER_HEADERS)
    assert center["packages_inducted_count"] == 500
    assert center["wip_package_count"] == 400
    assert center["exception_hold_count"] == 50
    assert center["disposed_package_count"] == 0
    assert center["missort_corrected_count"] == 0

    lane = _lane(api, lane_id, OPS_MANAGER_HEADERS)
    assert lane["sorted_package_count"] == 50, (
        "100 packages were scanned into the lane and 50 were pulled back out"
    )

    assert_package_conservation(center, _all_lanes(api, center_id))

    assert center["ops_posture"] == "OPEN"
    assert center["open_jam_count"] == 0
    assert center["open_serious_injury_count"] == 0
