"""Role-authorization corner cases for the Package Sortation Peak Staffing API.

Every test builds its own world through the documented endpoints, because the
harness restarts the API server (and empties the database) before each test.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ERR_FORBIDDEN_ROLE, ERR_SEGREGATION_OF_DUTIES
from test_helpers.assertions import (
    expected_planned_labor_cents,
    expected_provisional_cost_per_package,
)
from test_helpers.fixtures import parse_instant
from test_helpers.test_users import (
    FACILITY_ADMIN_HEADERS,
    INBOUND_COORDINATOR_HEADERS,
    LABOR_PLANNER_HEADERS,
    OPS_MANAGER_HEADERS,
    SORT_SUPERVISOR_HEADERS,
    make_headers,
    make_worker_headers,
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


def _plan(api, plan_id):
    return _read(api, f"/sortation/shift-plans/{plan_id}", LABOR_PLANNER_HEADERS)


def _load(api, load_id):
    return _read(api, f"/sortation/outbound-loads/{load_id}", SORT_SUPERVISOR_HEADERS)


def _staff_assignment(api, assignment_id):
    return _read(
        api, f"/sortation/staff-assignments/{assignment_id}", LABOR_PLANNER_HEADERS
    )


def _approve(api, center_id, plan_id, approver_id=None, center_version=None):
    """Approve a submitted plan, pinning the center version the caller last saw."""
    version = (
        center_version
        if center_version is not None
        else _center(api, center_id, OPS_MANAGER_HEADERS)["version"]
    )
    headers = (
        make_headers(approver_id, "OpsManager") if approver_id else OPS_MANAGER_HEADERS
    )
    return api.approve_shift_plan(plan_id, f.approve_payload(version), headers)


# ─── Tests ────────────────────────────────────────────

def test_sort_supervisor_cannot_clock_in_for_a_worker(api, world):
    """PRD §2.1: "If both headers are well formed but the named role is not authorized for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/supervisor_cannot_clock_in_for_a_worker
    """
    world.set_clock("2026-08-03T05:00:00Z")
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    chute = world.create_chute(center["id"], chute_number=1, throughput_pph=1200)
    plan = world.create_submitted_plan(
        center["id"],
        shift_date="2026-08-03",
        shift_window_start="2026-08-03T06:00:00Z",
        shift_window_end="2026-08-03T14:00:00Z",
        forecast_volume=4000,
        planned_core_headcount=4,
        planned_seasonal_headcount=0,
        labor_budget_cents=100000,
    )
    validate_success(_approve(api, center["id"], plan["id"]))
    worker = world.create_certified_worker(center["id"], full_name="Clocking Cleo")
    assignment = world.create_assignment(plan["id"], worker["id"], chute["id"])
    world.set_clock("2026-08-03T06:00:00Z")

    validate_error(
        api.check_in(assignment["id"], SORT_SUPERVISOR_HEADERS), ERR_FORBIDDEN_ROLE
    )
    refused = _staff_assignment(api, assignment["id"])
    assert refused["status"] == "ASSIGNED"
    assert refused["checked_in_at"] is None

    clocked_in = validate_success(
        api.check_in(assignment["id"], make_worker_headers(worker["id"]))
    )
    assert clocked_in["status"] == "CHECKED_IN"
    assert parse_instant(clocked_in["checked_in_at"]) == parse_instant(
        "2026-08-03T06:00:00Z"
    )

    assert _plan(api, plan["id"])["committed_headcount"] == 4, (
        "a CHECKED_IN row still counts as committed"
    )


def test_labor_planner_cannot_dispatch_but_ops_manager_can(api, world):
    """PRD §2.1: "If both headers are well formed but the named role is not authorized for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/labor_planner_cannot_dispatch_but_ops_manager_can
    """
    world.set_clock("2026-08-03T09:00:00Z")
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    center_id = center["id"]
    inbound_door = world.create_door(center_id, door_number=1, kind="INBOUND")
    outbound_door = world.create_door(center_id, door_number=2, kind="OUTBOUND")
    chute = world.create_chute(center_id, chute_number=1, throughput_pph=1200)
    lane = world.create_lane(center_id, forecast_hourly_volume=3000)
    world.map_lane_to_chute(
        chute["id"],
        lane["id"],
        expected_chute_version=chute["version"],
        window_start="2026-08-03T06:00:00Z",
        window_end="2026-08-03T14:00:00Z",
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
        dispatch_cut_time="2026-08-03T13:00:00Z",
    )
    world.scan(load["id"], small_count=100)
    world.close_load(load["id"])
    world.seal(load["id"])

    validate_error(
        api.dispatch_load(load["id"], LABOR_PLANNER_HEADERS), ERR_FORBIDDEN_ROLE
    )
    refused = _load(api, load["id"])
    assert refused["load_status"] == "LOADED"
    assert refused["seal_status"] == "SEALED"
    assert refused["dispatched_at"] is None

    dispatched = validate_success(api.dispatch_load(load["id"], OPS_MANAGER_HEADERS))
    assert dispatched["load_status"] == "DISPATCHED"
    assert parse_instant(dispatched["dispatched_at"]) == parse_instant(
        "2026-08-03T09:00:00Z"
    )
    assert float(dispatched["cube_used_cuft"]) == 33.50
    assert dispatched["package_count"] == 100


def test_plan_submitter_cannot_approve_or_reject_its_own_plan(api, world):
    """PRD §2.1: "The opaque operator identifier that submitted a plan is retained on the plan, and an `OpsManager` whose `X-User-ID` equals that stored submitter may neither approve nor reject the plan; both attempts are rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/segregation_of_duties_blocks_self_approval
    """
    dual_user = "operator-dual-1"
    world.set_clock("2026-08-03T05:00:00Z")
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    world.create_chute(center["id"], chute_number=1, throughput_pph=1200)
    plan = world.create_submitted_plan(
        center["id"],
        submitter_id=dual_user,
        shift_date="2026-08-03",
        shift_window_start="2026-08-03T06:00:00Z",
        shift_window_end="2026-08-03T14:00:00Z",
        forecast_volume=4000,
        planned_core_headcount=4,
        planned_seasonal_headcount=0,
        labor_budget_cents=100000,
    )
    assert plan["submitted_by_user_id"] == dual_user
    pinned_version = _center(api, center["id"], OPS_MANAGER_HEADERS)["version"]

    validate_error(
        _approve(
            api,
            center["id"],
            plan["id"],
            approver_id=dual_user,
            center_version=pinned_version,
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )
    assert _plan(api, plan["id"])["status"] == "SUBMITTED"

    validate_error(
        api.reject_shift_plan(
            plan["id"],
            f.reject_payload(rejection_reason="changed my mind about my own plan"),
            make_headers(dual_user, "OpsManager"),
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )
    still_submitted = _plan(api, plan["id"])
    assert still_submitted["status"] == "SUBMITTED"
    assert still_submitted["rejection_reason"] is None

    approved = validate_success(
        _approve(api, center["id"], plan["id"], center_version=pinned_version)
    )
    assert approved["status"] == "APPROVED", (
        "the refused calls consumed no center version, so the same pin still matches"
    )
    assert approved["approved_by_user_id"] == OPS_MANAGER_HEADERS["X-User-ID"]
    assert approved["planned_labor_cents"] == expected_planned_labor_cents(4, 0, 0, 8.0)
    assert approved["planned_labor_cents"] == 68800
    assert float(
        approved["provisional_cost_per_package_cents"]
    ) == expected_provisional_cost_per_package(68800, 4000)
    assert float(approved["provisional_cost_per_package_cents"]) == 20.20


def test_center_read_is_shared_across_every_role(api, world):
    """PRD §2.1: "If both headers are well formed but the named role is not authorized for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/center_read_is_shared_across_every_role
    """
    world.set_clock("2026-08-03T06:00:00Z")
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    worker = world.create_worker(center["id"], full_name="Reader Rae")

    callers = [
        FACILITY_ADMIN_HEADERS,
        INBOUND_COORDINATOR_HEADERS,
        SORT_SUPERVISOR_HEADERS,
        LABOR_PLANNER_HEADERS,
        OPS_MANAGER_HEADERS,
        make_worker_headers(worker["id"]),
    ]
    bodies = [_center(api, center["id"], headers) for headers in callers]

    for headers, body in zip(callers, bodies):
        assert body == bodies[0], (
            f"the {headers['X-User-Role']} projection differs from the FacilityAdmin one"
        )
        assert body["code"] == center["code"]
        assert body["ops_posture"] == "OPEN"
        assert body["flex_pool_total"] == 20
        assert body["flex_pool_available"] == 20
        assert body["flex_pool_reserved"] == 0
