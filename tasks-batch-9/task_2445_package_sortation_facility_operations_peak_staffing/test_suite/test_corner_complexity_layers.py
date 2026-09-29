"""Cross-cutting corner cases: version pinning, posture thresholds and derived
counter reconciliation for the Package Sortation Peak Staffing API.

Every test builds its own world through the documented endpoints, because the
harness restarts the API server (and empties the database) before each test.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_STALE_CENTER_VERSION,
    ERR_STALE_CHUTE_VERSION,
)
from test_helpers.assertions import assert_package_conservation
from test_helpers.fixtures import parse_instant
from test_helpers.test_users import (
    FACILITY_ADMIN_HEADERS,
    LABOR_PLANNER_HEADERS,
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


def _chute(api, chute_id):
    return _read(api, f"/sortation/sort-chutes/{chute_id}", SORT_SUPERVISOR_HEADERS)


def _lane(api, lane_id):
    return _read(api, f"/sortation/destination-lanes/{lane_id}", FACILITY_ADMIN_HEADERS)


def _plan(api, plan_id):
    return _read(api, f"/sortation/shift-plans/{plan_id}", LABOR_PLANNER_HEADERS)


# ─── Tests ────────────────────────────────────────────

def test_stale_chute_version_refused_then_current_version_accepted(api, world):
    """PRD §2.6: "Creating a chute assignment must carry `expected_chute_version` holding the client's last observed `version` of the target sortation chute."

    PRD §2.6: "If that value does not equal the chute's current `version`, the create is rejected with `ERR_STALE_CHUTE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_chute_version_refused_then_current_version_accepted
    """
    world.set_clock("2026-08-03T09:00:00Z")
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    chute = world.create_chute(
        center["id"],
        chute_number=1,
        throughput_pph=1200,
        max_concurrent_destinations=2,
    )
    stale_version = chute["version"]
    west = world.create_lane(
        center["id"], lane_code="L-WEST", region="WEST", forecast_hourly_volume=3000
    )
    east = world.create_lane(
        center["id"], lane_code="L-EAST", region="EAST", forecast_hourly_volume=2000
    )
    window = {
        "window_start": "2026-08-03T06:00:00Z",
        "window_end": "2026-08-03T14:00:00Z",
    }
    world.map_lane_to_chute(
        chute["id"], west["id"], expected_chute_version=stale_version, **window
    )

    validate_error(
        api.create_chute_assignment(
            f.chute_assignment_payload(
                chute["id"], east["id"], stale_version, **window
            ),
            SORT_SUPERVISOR_HEADERS,
        ),
        ERR_STALE_CHUTE_VERSION,
    )

    fresh_version = _chute(api, chute["id"])["version"]
    assert fresh_version == stale_version + 1, (
        "only the first mapping advanced the chute; the refused create consumed nothing"
    )

    created = validate_success(
        api.create_chute_assignment(
            f.chute_assignment_payload(
                chute["id"], east["id"], fresh_version, **window
            ),
            SORT_SUPERVISOR_HEADERS,
        ),
        201,
    )
    assert created["status"] == "ACTIVE"
    assert _chute(api, chute["id"])["version"] == fresh_version + 1

    assert _lane(api, west["id"])["assigned_capacity_pph"] == 1200
    assert _lane(api, east["id"])["assigned_capacity_pph"] == 1200


def test_stale_center_version_refused_at_approve_and_at_close(api, world):
    """PRD §2.6: "Approving a shift plan must carry `expected_center_version` holding the client's last observed `version` of the owning sort center, and closing a shift plan must do the same."

    PRD §2.6: "A mismatch against the center's current `version` is rejected with `ERR_STALE_CENTER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_center_version_refused_at_approve_and_at_close
    """
    world.set_clock("2026-08-03T05:00:00Z")
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    center_id = center["id"]
    world.create_chute(center_id, chute_number=1, throughput_pph=1200)
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
    stale_version = _center(api, center_id, OPS_MANAGER_HEADERS)["version"]
    validate_success(
        api.patch_sort_center(
            center_id, f.sort_center_patch_payload(71.00), FACILITY_ADMIN_HEADERS
        )
    )

    validate_error(
        api.approve_shift_plan(
            plan["id"], f.approve_payload(stale_version), OPS_MANAGER_HEADERS
        ),
        ERR_STALE_CENTER_VERSION,
    )
    assert _plan(api, plan["id"])["status"] == "SUBMITTED"

    approve_version = _center(api, center_id, OPS_MANAGER_HEADERS)["version"]
    approved = validate_success(
        api.approve_shift_plan(
            plan["id"], f.approve_payload(approve_version), OPS_MANAGER_HEADERS
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["flex_draw_count"] == 0

    validate_error(
        api.close_shift_plan(
            plan["id"], f.close_plan_payload(approve_version), OPS_MANAGER_HEADERS
        ),
        ERR_STALE_CENTER_VERSION,
    )

    close_version = _center(api, center_id, OPS_MANAGER_HEADERS)["version"]
    assert close_version == approve_version + 1, (
        "the successful approve incremented the center's version by exactly one"
    )
    closed = validate_success(
        api.close_shift_plan(
            plan["id"], f.close_plan_payload(close_version), OPS_MANAGER_HEADERS
        )
    )
    assert closed["status"] == "CLOSED"
    assert closed["actual_labor_cents"] == 0

    settled_center = _center(api, center_id)
    assert settled_center["flex_pool_available"] == 20
    assert settled_center["flex_pool_reserved"] == 0


def test_third_concurrent_jam_hold_freezes_the_center(api, world):
    """PRD §2.5: "Because the `FROZEN` test is applied first, a center with one open serious injury is frozen even when no jam is held and every lane is quiet; and a center with three held jams is frozen rather than merely restricted."

    PRD §2.5: "Otherwise the posture is `RESTRICTED` when at least one jam is held, or when the peak lane pressure among active lanes is greater than or equal to 1.50, or when the center's `automation_utilization_pct` is below 45."

    Design: Corner/cross_cutting_complexity_layers/third_concurrent_jam_hold_freezes_the_center
    """
    clock = "2026-08-03T06:00:00Z"
    world.set_clock(clock)
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    center_id = center["id"]
    window = {
        "window_start": "2026-08-03T06:00:00Z",
        "window_end": "2026-08-03T07:00:00Z",
    }
    doors = [
        world.create_door(center_id, door_number=number, kind="INBOUND")
        for number in (1, 2, 3)
    ]
    chutes = [
        world.create_chute(center_id, chute_number=number, throughput_pph=1200)
        for number in (1, 2, 3)
    ]
    appointments = [
        world.unloading_appointment(
            center_id, door["id"], manifest_package_count=1000, **window
        )
        for door in doors
    ]

    quiet = _center(api, center_id)
    assert quiet["ops_posture"] == "OPEN"
    assert quiet["open_jam_count"] == 0
    previous_version = quiet["version"]

    world.jam_hold(appointments[0]["id"], chutes[0]["id"])
    after_first = _center(api, center_id)
    assert after_first["open_jam_count"] == 1
    assert after_first["ops_posture"] == "RESTRICTED"
    assert parse_instant(after_first["last_posture_change_at"]) == parse_instant(clock)
    assert after_first["version"] > previous_version

    world.jam_hold(appointments[1]["id"], chutes[1]["id"])
    after_second = _center(api, center_id)
    assert after_second["open_jam_count"] == 2
    assert after_second["ops_posture"] == "RESTRICTED", (
        "two held jams sit one short of the freeze threshold"
    )
    assert after_second["version"] > after_first["version"]

    world.jam_hold(appointments[2]["id"], chutes[2]["id"])
    after_third = _center(api, center_id)
    assert after_third["open_jam_count"] == 3
    assert after_third["ops_posture"] == "FROZEN"
    assert parse_instant(after_third["last_posture_change_at"]) == parse_instant(clock)
    assert after_third["version"] > after_second["version"]

    world.resume_unload(appointments[2]["id"], chutes[2]["id"])
    after_resume = _center(api, center_id)
    assert after_resume["open_jam_count"] == 2
    assert after_resume["ops_posture"] == "RESTRICTED", (
        "the threshold resets downward when a jam is cleared"
    )
    assert parse_instant(after_resume["last_posture_change_at"]) == parse_instant(clock)
    assert after_resume["version"] > after_third["version"]

    resumed_chute = _chute(api, chutes[2]["id"])
    assert resumed_chute["status"] == "ACTIVE"
    assert resumed_chute["jam_hold_count"] == 1


def test_dispose_and_relabel_reconcile_center_derived_counters(api, world):
    """PRD §3.8: "A `DISPOSE` adds `package_count` to the center's `disposed_package_count`, removing those packages from the network permanently."

    PRD §3.8: "A `RELABEL` returns `package_count` to the center's `wip_package_count`, putting the packages back in front of the sorter to be scanned again."

    Design: Corner/cross_cutting_complexity_layers/dispose_and_relabel_reconcile_center_derived_counters
    """
    world.set_clock("2026-08-03T09:00:00Z")
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    center_id = center["id"]
    inbound_door = world.create_door(center_id, door_number=1, kind="INBOUND")
    appointment = world.induct_packages(
        center_id,
        inbound_door["id"],
        500,
        window_start="2026-08-03T09:00:00Z",
        window_end="2026-08-03T10:00:00Z",
    )

    inducted = _center(api, center_id)
    assert inducted["packages_inducted_count"] == 500
    assert inducted["wip_package_count"] == 500
    version = inducted["version"]

    damaged = world.create_exception(
        center_id,
        exception_type="DAMAGED",
        package_count=50,
        trailer_appointment_id=appointment["id"],
    )
    after_damaged = _center(api, center_id)
    assert after_damaged["wip_package_count"] == 450
    assert after_damaged["exception_hold_count"] == 50
    assert after_damaged["disposed_package_count"] == 0
    assert after_damaged["version"] > version
    assert_package_conservation(after_damaged, [])
    version = after_damaged["version"]

    validate_success(
        api.resolve_package_exception(
            damaged["id"],
            f.resolve_exception_payload("DISPOSE"),
            SORT_SUPERVISOR_HEADERS,
        )
    )
    after_dispose = _center(api, center_id)
    assert after_dispose["exception_hold_count"] == 0
    assert after_dispose["disposed_package_count"] == 50
    assert after_dispose["wip_package_count"] == 450
    assert after_dispose["version"] > version
    assert_package_conservation(after_dispose, [])
    version = after_dispose["version"]

    unlabeled = world.create_exception(
        center_id,
        exception_type="UNLABELED",
        package_count=30,
        trailer_appointment_id=appointment["id"],
    )
    after_unlabeled = _center(api, center_id)
    assert after_unlabeled["wip_package_count"] == 420
    assert after_unlabeled["exception_hold_count"] == 30
    assert after_unlabeled["disposed_package_count"] == 50
    assert after_unlabeled["version"] > version
    assert_package_conservation(after_unlabeled, [])
    version = after_unlabeled["version"]

    validate_success(
        api.resolve_package_exception(
            unlabeled["id"],
            f.resolve_exception_payload("RELABEL"),
            SORT_SUPERVISOR_HEADERS,
        )
    )
    after_relabel = _center(api, center_id)
    assert after_relabel["exception_hold_count"] == 0
    assert after_relabel["wip_package_count"] == 450
    assert after_relabel["disposed_package_count"] == 50
    assert after_relabel["missort_corrected_count"] == 0, (
        "neither resolution was a REROUTE"
    )
    assert after_relabel["version"] > version
    assert after_relabel["ops_posture"] == "OPEN"
    assert_package_conservation(after_relabel, [])
