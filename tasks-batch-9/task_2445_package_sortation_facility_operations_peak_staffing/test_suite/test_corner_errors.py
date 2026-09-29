"""Error-triggerability corner cases for the Package Sortation Peak Staffing API.

Every test builds its own world through the documented endpoints, because the
harness restarts the API server (and empties the database) before each test.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_FACILITY_RESOURCE_NOT_FOUND,
    ERR_FLEX_POOL_EXHAUSTED,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_ASSIGNMENT_STATE,
    ERR_INVALID_EXCEPTION_STATE,
    ERR_LABOR_BUDGET_EXCEEDED,
    ERR_LABOR_RESOURCE_NOT_FOUND,
    ERR_NOT_ASSIGNMENT_OWNER,
    ERR_OUTBOUND_RESOURCE_NOT_FOUND,
    ERR_SORT_CENTER_NOT_FOUND,
    ERR_TRAILER_APPOINTMENT_NOT_FOUND,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import assert_package_conservation
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


def _staff_assignment(api, assignment_id):
    return _read(
        api, f"/sortation/staff-assignments/{assignment_id}", LABOR_PLANNER_HEADERS
    )


def _worker(api, worker_id):
    return _read(api, f"/sortation/workers/{worker_id}", LABOR_PLANNER_HEADERS)


def _exception(api, exception_id):
    return _read(
        api, f"/sortation/package-exceptions/{exception_id}", SORT_SUPERVISOR_HEADERS
    )


def _injury(api, report_id):
    return _read(api, f"/sortation/injury-reports/{report_id}", SORT_SUPERVISOR_HEADERS)


def _approve(api, center_id, plan_id, approver_id=None):
    """Approve a submitted plan against the center's current `version`."""
    version = _center(api, center_id, OPS_MANAGER_HEADERS)["version"]
    headers = (
        make_headers(approver_id, "OpsManager") if approver_id else OPS_MANAGER_HEADERS
    )
    return api.approve_shift_plan(plan_id, f.approve_payload(version), headers)


def _staffed_plan(api, world):
    """A center with one line and an APPROVED plan whose window contains the clock,
    plus one CERTIFIED worker holding an `ASSIGNED` staff assignment."""
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    chute = world.create_chute(center["id"], chute_number=1, throughput_pph=1200)
    plan = world.create_submitted_plan(
        center["id"],
        forecast_volume=4000,
        planned_core_headcount=4,
        planned_seasonal_headcount=0,
        labor_budget_cents=100000,
    )
    validate_success(_approve(api, center["id"], plan["id"]))
    worker = world.create_certified_worker(center["id"], full_name="Eager Ellis")
    assignment = world.create_assignment(plan["id"], worker["id"], chute["id"])
    return {
        "center": center,
        "chute": chute,
        "plan": plan,
        "worker": worker,
        "assignment": assignment,
    }


# ─── Tests ────────────────────────────────────────────

def test_auth_failures_are_unauthenticated_forbidden_role_and_not_owner(api, world):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the six role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs."

    PRD §2.1: "If both headers are well formed but the named role is not authorized for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    PRD §2.1: "Concretely, when a `Worker` clocks in or out of a staff assignment, the assignment's `worker_id` must equal `X-User-ID`, and a mismatch is rejected with `ERR_NOT_ASSIGNMENT_OWNER` (HTTP 403)."

    Design: Corner/errors/auth_errors_unauthenticated_forbidden_and_not_owner
    """
    built = _staffed_plan(api, world)
    center_id = built["center"]["id"]
    assignment_id = built["assignment"]["id"]
    other_worker = world.create_worker(center_id, full_name="Worker Two")

    role_less = {
        key: value
        for key, value in FACILITY_ADMIN_HEADERS.items()
        if key != "X-User-Role"
    }
    validate_error(
        api.request("GET", f"/sortation/sort-centers/{center_id}", headers=role_less),
        ERR_UNAUTHENTICATED,
    )

    undeclared_role = make_headers("operator-yard-marshal-1", "YardMarshal")
    validate_error(
        api.request(
            "GET", f"/sortation/sort-centers/{center_id}", headers=undeclared_role
        ),
        ERR_UNAUTHENTICATED,
    )

    validate_error(
        api.check_in(assignment_id, LABOR_PLANNER_HEADERS), ERR_FORBIDDEN_ROLE
    )

    validate_error(
        api.check_in(assignment_id, make_worker_headers(other_worker["id"])),
        ERR_NOT_ASSIGNMENT_OWNER,
    )

    after = _staff_assignment(api, assignment_id)
    assert after["status"] == "ASSIGNED"
    assert after["checked_in_at"] is None


def test_existence_failures_split_by_family_are_not_found(api, world):
    """PRD §2.7: "Beyond the center, existence failures are grouped by resource family so that the error identity itself tells the caller which family failed: a missing dock door, sortation chute, destination lane or chute assignment yields `ERR_FACILITY_RESOURCE_NOT_FOUND`; a missing trailer appointment yields `ERR_TRAILER_APPOINTMENT_NOT_FOUND`; a missing shift plan yields `ERR_SHIFT_PLAN_NOT_FOUND`; a missing worker or staff assignment yields `ERR_LABOR_RESOURCE_NOT_FOUND`; a missing outbound load or package exception yields `ERR_OUTBOUND_RESOURCE_NOT_FOUND`."

    PRD §2.7: "A center that does not exist yields `ERR_SORT_CENTER_NOT_FOUND` (HTTP 404), and the same error is produced when a request body names a `sort_center_id` that does not resolve."

    Design: Corner/errors/existence_errors_across_entity_families_not_found
    """
    unknown = NON_EXISTENT_UUID

    validate_error(
        api.request(
            "GET", f"/sortation/sort-centers/{unknown}", headers=FACILITY_ADMIN_HEADERS
        ),
        ERR_SORT_CENTER_NOT_FOUND,
    )

    validate_error(
        api.request(
            "GET", f"/sortation/sort-chutes/{unknown}", headers=FACILITY_ADMIN_HEADERS
        ),
        ERR_FACILITY_RESOURCE_NOT_FOUND,
    )

    validate_error(
        api.arrive_trailer_appointment(unknown, INBOUND_COORDINATOR_HEADERS),
        ERR_TRAILER_APPOINTMENT_NOT_FOUND,
    )

    validate_error(
        api.request(
            "GET", f"/sortation/workers/{unknown}", headers=LABOR_PLANNER_HEADERS
        ),
        ERR_LABOR_RESOURCE_NOT_FOUND,
    )

    validate_error(
        api.request(
            "GET", f"/sortation/outbound-loads/{unknown}", headers=SORT_SUPERVISOR_HEADERS
        ),
        ERR_OUTBOUND_RESOURCE_NOT_FOUND,
    )

    validate_error(
        api.create_package_exception(
            f.package_exception_payload(unknown), SORT_SUPERVISOR_HEADERS
        ),
        ERR_SORT_CENTER_NOT_FOUND,
    )


def test_check_out_before_check_in_is_refused(api, world):
    """PRD §3.7: "Checking in twice, or checking out an assignment that was never checked in, is refused with `ERR_INVALID_ASSIGNMENT_STATE`."

    Design: Corner/errors/check_out_before_check_in_refused
    """
    built = _staffed_plan(api, world)
    assignment_id = built["assignment"]["id"]
    worker_id = built["worker"]["id"]

    validate_error(
        api.check_out(assignment_id, make_worker_headers(worker_id)),
        ERR_INVALID_ASSIGNMENT_STATE,
    )

    untouched = _staff_assignment(api, assignment_id)
    assert untouched["status"] == "ASSIGNED"
    assert untouched["checked_in_at"] is None
    assert untouched["checked_out_at"] is None
    assert float(untouched["worked_hours"]) == 0.0

    worker = _worker(api, worker_id)
    assert worker["completed_assignment_count"] == 0
    assert worker["consecutive_completed_shifts"] == 0

    checked_in = validate_success(
        api.check_in(assignment_id, make_worker_headers(worker_id))
    )
    assert checked_in["status"] == "CHECKED_IN"

    validate_error(
        api.check_in(assignment_id, make_worker_headers(worker_id)),
        ERR_INVALID_ASSIGNMENT_STATE,
    )
    assert _staff_assignment(api, assignment_id)["status"] == "CHECKED_IN"


def test_second_resolve_and_second_close_are_refused(api, world):
    """PRD §3.8: "An exception that is already `RESOLVED` is refused with `ERR_INVALID_EXCEPTION_STATE`, and a frozen center refuses resolution with `ERR_CENTER_FROZEN`."

    PRD §3.9: "The report must be `OPEN`; closing an already-closed report is refused with `ERR_INVALID_EXCEPTION_STATE`."

    Design: Corner/errors/resolving_and_closing_twice_refused
    """
    center = world.create_center(automation_utilization_pct=70.00, flex_pool_total=20)
    center_id = center["id"]
    inbound_door = world.create_door(center_id, door_number=1, kind="INBOUND")
    world.induct_packages(center_id, inbound_door["id"], 500)
    exception = world.create_exception(
        center_id, exception_type="DAMAGED", package_count=50
    )
    worker = world.create_worker(center_id, full_name="Bruised Bailey")
    injury = world.file_injury(
        center_id, worker["id"], severity="FIRST_AID", body_part="FINGER"
    )

    resolved = validate_success(
        api.resolve_package_exception(
            exception["id"],
            f.resolve_exception_payload("DISPOSE"),
            SORT_SUPERVISOR_HEADERS,
        )
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "DISPOSE"
    after_first = _center(api, center_id)
    assert after_first["disposed_package_count"] == 50
    assert after_first["exception_hold_count"] == 0

    validate_error(
        api.resolve_package_exception(
            exception["id"],
            f.resolve_exception_payload("DISPOSE"),
            SORT_SUPERVISOR_HEADERS,
        ),
        ERR_INVALID_EXCEPTION_STATE,
    )
    after_second = _center(api, center_id)
    assert after_second["disposed_package_count"] == 50, (
        "the refused second resolve must not debit the pool twice"
    )
    assert _exception(api, exception["id"])["status"] == "RESOLVED"

    closed = validate_success(
        api.close_injury_report(
            injury["id"], f.close_injury_payload(1), OPS_MANAGER_HEADERS
        )
    )
    assert closed["status"] == "CLOSED"
    assert closed["lost_time_days"] == 1

    validate_error(
        api.close_injury_report(
            injury["id"], f.close_injury_payload(1), OPS_MANAGER_HEADERS
        ),
        ERR_INVALID_EXCEPTION_STATE,
    )
    still_closed = _injury(api, injury["id"])
    assert still_closed["status"] == "CLOSED"
    assert still_closed["lost_time_days"] == 1

    final_center = _center(api, center_id)
    assert final_center["wip_package_count"] == 450
    assert final_center["exception_hold_count"] == 0
    assert final_center["disposed_package_count"] == 50
    assert_package_conservation(final_center, [])


def test_flex_pool_exhausted_and_labor_budget_exceeded_are_rejected(api, world):
    """PRD §3.5: "The bench gate then requires the center's `flex_pool_available` to be greater than or equal to the needed flex, refusing with `ERR_FLEX_POOL_EXHAUSTED` when the bench is short — this is the point at which two centers' worth of ambition meets one bench, and it is why approvals of different plans race through version pinning."

    PRD §3.5: "The budget gate compares that post-premium `planned_labor_cents` against the plan's `labor_budget_cents` and refuses with `ERR_LABOR_BUDGET_EXCEEDED` (HTTP 402) when the priced shift is the larger."

    Design: Corner/errors/flex_pool_exhausted_then_labor_budget_exceeded_rejected
    """
    thin_bench = world.create_center(
        automation_utilization_pct=70.00, flex_pool_total=1, name="Thin Flex Pool"
    )
    world.create_chute(thin_bench["id"], chute_number=1, throughput_pph=1200)
    bench_plan = world.create_submitted_plan(
        thin_bench["id"],
        forecast_volume=40000,
        planned_core_headcount=0,
        planned_seasonal_headcount=0,
        labor_budget_cents=1000000,
    )
    assert bench_plan["required_headcount"] == 6, (
        "40000 packages over 950 per associate per hour across 8 hours needs 6 bodies"
    )

    thin_budget = world.create_center(
        automation_utilization_pct=70.00, flex_pool_total=20, name="Thin Budget"
    )
    world.create_chute(thin_budget["id"], chute_number=1, throughput_pph=1200)
    budget_plan = world.create_submitted_plan(
        thin_budget["id"],
        forecast_volume=40000,
        planned_core_headcount=6,
        planned_seasonal_headcount=0,
        labor_budget_cents=100000,
    )
    assert budget_plan["required_headcount"] == 6

    validate_error(
        _approve(api, thin_bench["id"], bench_plan["id"]),
        ERR_FLEX_POOL_EXHAUSTED,
    )
    bench_center = _center(api, thin_bench["id"])
    assert bench_center["flex_pool_available"] == 1
    assert bench_center["flex_pool_reserved"] == 0
    bench_after = _plan(api, bench_plan["id"])
    assert bench_after["status"] == "SUBMITTED"
    assert bench_after["flex_draw_count"] == 0

    validate_error(
        _approve(api, thin_budget["id"], budget_plan["id"]),
        ERR_LABOR_BUDGET_EXCEEDED,
    )
    budget_after = _plan(api, budget_plan["id"])
    assert budget_after["status"] == "SUBMITTED"
    assert budget_after["planned_labor_cents"] == 0, (
        "a refused approve writes no cost: the drafted plan's 0 still stands"
    )
    assert budget_after["provisional_cost_per_package_cents"] is None
    budget_center = _center(api, thin_budget["id"])
    assert budget_center["flex_pool_available"] == 20
    assert budget_center["flex_pool_reserved"] == 0
