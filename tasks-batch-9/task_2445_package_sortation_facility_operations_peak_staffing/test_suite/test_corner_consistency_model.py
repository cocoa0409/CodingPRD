"""Consistency-model corner case for the Package Sortation Peak Staffing API.

The test builds its own world through the documented endpoints, because the
harness restarts the API server (and empties the database) before each test.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_package_conservation,
    expected_batch_cube,
    expected_cube_utilization_pct,
)
from test_helpers.test_users import (
    FACILITY_ADMIN_HEADERS,
    OPS_MANAGER_HEADERS,
    SORT_SUPERVISOR_HEADERS,
)


# ─── Local read helpers ───────────────────────────────
# Reads go through the client's raw request channel so the caller's headers
# travel as headers.

def _read(api, path, headers, params=None):
    """GET one resource and return its `data` payload."""
    return validate_success(api.request("GET", path, headers=headers, params=params))


def _center(api, center_id, headers=None):
    return _read(
        api, f"/sortation/sort-centers/{center_id}", headers or FACILITY_ADMIN_HEADERS
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


# ─── Tests ────────────────────────────────────────────

def test_scan_response_already_reflects_every_derived_field(api, world):
    """PRD §2.10: "By the time the response is written, every downstream row has already been updated and every derived aggregate has already been recomputed, so a read immediately after the request observes the finished picture."

    Design: Corner/consistency_model/mutation_response_already_reflects_every_derived_field
    """
    world.set_clock("2026-08-03T09:00:00Z")
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    center_id = center["id"]
    inbound_door = world.create_door(center_id, door_number=1, kind="INBOUND")
    outbound_door = world.create_door(center_id, door_number=2, kind="OUTBOUND")
    chute = world.create_chute(center_id, chute_number=1, throughput_pph=1200)
    lane = world.create_lane(
        center_id, lane_code="L-WEST", region="WEST", forecast_hourly_volume=3000
    )
    world.map_lane_to_chute(
        chute["id"],
        lane["id"],
        expected_chute_version=chute["version"],
        window_start="2026-08-03T06:00:00Z",
        window_end="2026-08-03T14:00:00Z",
    )
    plan = world.create_submitted_plan(
        center_id,
        shift_date="2026-08-03",
        shift_window_start="2026-08-03T06:00:00Z",
        shift_window_end="2026-08-03T14:00:00Z",
        forecast_volume=4000,
        planned_core_headcount=4,
        planned_seasonal_headcount=0,
        labor_budget_cents=100000,
    )
    approve_version = _center(api, center_id, OPS_MANAGER_HEADERS)["version"]
    validate_success(
        api.approve_shift_plan(
            plan["id"], f.approve_payload(approve_version), OPS_MANAGER_HEADERS
        )
    )
    world.induct_packages(
        center_id,
        inbound_door["id"],
        500,
        window_start="2026-08-03T09:00:00Z",
        window_end="2026-08-03T10:00:00Z",
    )
    load = world.stage_load(
        center_id,
        outbound_door["id"],
        lane["id"],
        trailer_cube_cuft=1000.00,
        dispatch_cut_time="2026-08-03T13:00:00Z",
    )

    expected_cube = expected_batch_cube(small=200, medium=100)
    assert expected_cube == 187.50
    expected_utilization = expected_cube_utilization_pct(expected_cube, 1000.00)
    assert expected_utilization == 18.75

    scanned = validate_success(
        api.scan_packages(
            load["id"],
            f.scan_packages_payload(small_count=200, medium_count=100),
            SORT_SUPERVISOR_HEADERS,
        )
    )
    assert scanned["load_status"] == "LOADING"
    assert scanned["package_count"] == 300
    assert float(scanned["cube_used_cuft"]) == expected_cube
    assert float(scanned["cube_utilization_pct"]) == expected_utilization

    read_back = _read(
        api, f"/sortation/outbound-loads/{load['id']}", SORT_SUPERVISOR_HEADERS
    )
    assert read_back["load_status"] == "LOADING"
    assert read_back["package_count"] == 300
    assert float(read_back["cube_used_cuft"]) == expected_cube
    assert float(read_back["cube_utilization_pct"]) == expected_utilization

    center_after = _center(api, center_id, SORT_SUPERVISOR_HEADERS)
    assert center_after["packages_inducted_count"] == 500
    assert center_after["wip_package_count"] == 200
    assert center_after["exception_hold_count"] == 0
    assert center_after["disposed_package_count"] == 0

    lane_after = _read(
        api, f"/sortation/destination-lanes/{lane['id']}", SORT_SUPERVISOR_HEADERS
    )
    assert lane_after["sorted_package_count"] == 300

    plan_after = _read(
        api, f"/sortation/shift-plans/{plan['id']}", OPS_MANAGER_HEADERS
    )
    assert plan_after["sorted_package_count"] == 300, (
        "the clock sits inside this plan's shift window, so the scan is attributed to it"
    )

    assert_package_conservation(center_after, _all_lanes(api, center_id))
