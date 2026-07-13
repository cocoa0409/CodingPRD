"""Composite setup helpers.

Every helper builds its preconditions from scratch against an empty database,
using only PRD-declared endpoints. Setup calls go through get_success_data() so
a broken precondition surfaces as a clear "Setup step failed" rather than a
confusing assertion deep inside a test.

Identity threading: a VendorTech's X-User-ID is the acting Vendor's id and a
TenantRep's X-User-ID is the acting Lease's id, so every ownership-gated call
below is made with make_vendor_tech_headers(vendor["id"]) /
make_tenant_rep_headers(lease["id"]) — never the shared fallback constant.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_STARTUP_DEFAULT
from .factories import (
    allocation_payload,
    asset_payload,
    building_payload,
    capital_project_payload,
    dispatch_completion_payload,
    dispatch_payload,
    lease_payload,
    pm_plan_payload,
    shift_payload,
    space_payload,
    statement_payload,
    utility_reading_payload,
    vendor_payload,
    work_order_payload,
)
from .test_users import (
    FC_APPROVER_ID,
    FC_PROPOSER_ID,
    TEST_USERS,
    make_finance_controller_headers,
    make_tenant_rep_headers,
    make_vendor_tech_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
FM = TEST_USERS["facility_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]
FC2 = TEST_USERS["finance_approver_headers"]
SA = TEST_USERS["sustainability_analyst_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-resource primitives
# ---------------------------------------------------------------------------
def set_clock(iso8601: str) -> str:
    """Move the logical clock. Returns the confirmed current_utc."""
    data = get_success_data(api_client.set_clock(iso8601, ADMIN))
    return data.get("current_utc", iso8601)


def create_building(**overrides) -> dict:
    return get_success_data(
        api_client.create_building(building_payload(**overrides), FM)
    )


def create_space(building_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_space(building_id, space_payload(**overrides), FM)
    )


def create_asset(building_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_asset(asset_payload(building_id, **overrides), FM)
    )


def create_pm_plan(asset_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_pm_plan(pm_plan_payload(asset_id, **overrides), FM)
    )


def create_vendor(**overrides) -> dict:
    return get_success_data(api_client.create_vendor(vendor_payload(**overrides), FM))


def create_work_order(building_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_work_order(work_order_payload(building_id, **overrides), FM)
    )


def create_utility_reading(building_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_utility_reading(
            utility_reading_payload(building_id, **overrides), SA
        )
    )


def create_lease(building_id, **overrides) -> dict:
    return get_success_data(api_client.create_lease(lease_payload(building_id, **overrides), FC))


def create_allocation(lease_id, space_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_allocation(
            lease_id, allocation_payload(space_id, **overrides), FC
        )
    )


def activate_lease(lease_id) -> dict:
    return get_success_data(api_client.activate_lease(lease_id, FC))


def create_shift(building_id, vendor_id, zone_space_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_shift(
            shift_payload(building_id, vendor_id, zone_space_id, **overrides), FM
        )
    )


def ops_run(building_id) -> dict:
    return get_success_data(api_client.ops_run(building_id, FM))


def read_work_order(work_order_id) -> dict:
    return get_success_data(api_client.get_work_order(work_order_id, FM))


def read_lease(lease_id) -> dict:
    return get_success_data(api_client.get_lease(lease_id, FC))


def read_lease_version(lease_id) -> int:
    """Statement creation is OCC-guarded on the lease, so its version must be
    re-read before every create."""
    return read_lease(lease_id)["version"]


def read_work_order_version(work_order_id) -> int:
    """Dispatch creation is OCC-guarded on the work order."""
    return read_work_order(work_order_id)["version"]


def read_building(building_id) -> dict:
    return get_success_data(api_client.get_building(building_id, FM))


def read_asset(asset_id) -> dict:
    return get_success_data(api_client.get_asset(asset_id, FM))


def read_vendor(vendor_id) -> dict:
    return get_success_data(api_client.get_vendor(vendor_id, FM))


def read_dispatch(dispatch_id) -> dict:
    return get_success_data(api_client.get_dispatch(dispatch_id, FM))


def read_space(space_id) -> dict:
    return get_success_data(api_client.get_space(space_id, FC))


def read_statement(statement_id) -> dict:
    return get_success_data(api_client.get_statement(statement_id, FC))


def read_capital_project(project_id) -> dict:
    return get_success_data(api_client.get_capital_project(project_id, FC))


def read_pm_plan(asset_id, pm_plan_id) -> dict:
    plans = get_success_data(api_client.list_asset_pm_plans(asset_id, FM))
    for plan in plans:
        if plan["id"] == pm_plan_id:
            return plan
    raise AssertionError(f"Setup step failed: PM plan {pm_plan_id} not found on asset {asset_id}")


def report_failure(asset_id) -> dict:
    return get_success_data(api_client.report_asset_failure(asset_id, FM))


# ---------------------------------------------------------------------------
# Tier 1: state progression on a single work order
# ---------------------------------------------------------------------------
def dispatch_work_order(work_order_id, vendor_id) -> dict:
    """Dispatch with a freshly-read expected_work_order_version."""
    version = read_work_order_version(work_order_id)
    return get_success_data(
        api_client.create_dispatch(
            work_order_id, dispatch_payload(vendor_id, version), FM
        )
    )


def accept_dispatch(dispatch_id, vendor_id) -> dict:
    return get_success_data(
        api_client.accept_dispatch(dispatch_id, make_vendor_tech_headers(vendor_id))
    )


def decline_dispatch(dispatch_id, vendor_id, reason=None) -> dict:
    payload = {"reason": reason} if reason is not None else {}
    return get_success_data(
        api_client.decline_dispatch(
            dispatch_id, make_vendor_tech_headers(vendor_id), payload
        )
    )


def complete_dispatch(dispatch_id, vendor_id, actual_labor_hours=1, actual_parts_cost=0) -> dict:
    return get_success_data(
        api_client.complete_dispatch(
            dispatch_id,
            dispatch_completion_payload(
                actual_labor_hours=actual_labor_hours,
                actual_parts_cost=actual_parts_cost,
            ),
            make_vendor_tech_headers(vendor_id),
        )
    )


def qa_work_order(work_order_id, outcome) -> dict:
    return get_success_data(
        api_client.qa_work_order(work_order_id, {"outcome": outcome}, FM)
    )


def complete_shift(shift_id, vendor_id, actual_headcount) -> dict:
    return get_success_data(
        api_client.complete_shift(
            shift_id,
            {"actual_headcount": actual_headcount},
            make_vendor_tech_headers(vendor_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — building + vendor + work order
# ---------------------------------------------------------------------------
def setup_building_and_vendor(clock="2026-05-04T09:00:00Z", vendor_overrides=None,
                              building_overrides=None) -> dict:
    """Clock at a business-hours instant, one OPEN building, one HVAC vendor."""
    if clock:
        set_clock(clock)
    building = create_building(**(building_overrides or {}))
    vendor = create_vendor(**(vendor_overrides or {}))
    return {"building": building, "vendor": vendor}


def setup_work_order_dispatched(clock="2026-05-04T09:00:00Z", wo_overrides=None,
                                vendor_overrides=None) -> dict:
    """Building + vendor + one NEW work order dispatched to that vendor (OFFERED)."""
    base = setup_building_and_vendor(clock=clock, vendor_overrides=vendor_overrides)
    building, vendor = base["building"], base["vendor"]
    work_order = create_work_order(building["id"], **(wo_overrides or {}))
    dispatch = dispatch_work_order(work_order["id"], vendor["id"])
    return {
        "building": building,
        "vendor": vendor,
        "work_order": read_work_order(work_order["id"]),
        "work_order_at_create": work_order,
        "dispatch": dispatch,
    }


def setup_work_order_pending_qa(clock="2026-05-04T09:00:00Z",
                                accept_clock=None,
                                complete_clock="2026-05-04T10:00:00Z",
                                actual_labor_hours=2, actual_parts_cost=0,
                                wo_overrides=None, vendor_overrides=None) -> dict:
    """Dispatch → accept → complete. The work order lands in PENDING_QA with a
    settled billable_amount; the dispatch is COMPLETED."""
    ctx = setup_work_order_dispatched(
        clock=clock, wo_overrides=wo_overrides, vendor_overrides=vendor_overrides
    )
    if accept_clock:
        set_clock(accept_clock)
    accept_dispatch(ctx["dispatch"]["id"], ctx["vendor"]["id"])
    if complete_clock:
        set_clock(complete_clock)
    dispatch = complete_dispatch(
        ctx["dispatch"]["id"], ctx["vendor"]["id"],
        actual_labor_hours=actual_labor_hours, actual_parts_cost=actual_parts_cost,
    )
    ctx["dispatch"] = dispatch
    ctx["work_order"] = read_work_order(ctx["work_order"]["id"])
    return ctx


def setup_closed_work_order(clock="2026-05-04T09:00:00Z",
                            complete_clock="2026-05-04T10:00:00Z",
                            actual_labor_hours=2, actual_parts_cost=0,
                            wo_overrides=None, vendor_overrides=None) -> dict:
    """Full pipeline through QA PASS: the work order ends CLOSED."""
    ctx = setup_work_order_pending_qa(
        clock=clock, complete_clock=complete_clock,
        actual_labor_hours=actual_labor_hours, actual_parts_cost=actual_parts_cost,
        wo_overrides=wo_overrides, vendor_overrides=vendor_overrides,
    )
    qa_work_order(ctx["work_order"]["id"], "PASS")
    ctx["work_order"] = read_work_order(ctx["work_order"]["id"])
    ctx["dispatch"] = read_dispatch(ctx["dispatch"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: posture — freezing and restricting a building
# ---------------------------------------------------------------------------
def setup_frozen_building(clock="2026-05-04T09:00:00Z", with_pm_plan=False,
                          with_shift=False) -> dict:
    """A CRITICAL asset fails, driving oos_critical_asset_count to 1 and the
    building's posture to FROZEN. Optionally seeds an ACTIVE PM plan and a
    SCHEDULED janitorial shift first, so the freeze cascade has something to hit."""
    if clock:
        set_clock(clock)
    building = create_building()
    zone = None
    janitor = None
    shift = None
    plan = None

    asset = create_asset(
        building["id"], asset_tag="CHILLER-01", category="HVAC", criticality="CRITICAL"
    )
    if with_pm_plan:
        plan = create_pm_plan(asset["id"], next_due_at="2026-06-01T00:00:00Z")
    if with_shift:
        zone = create_space(building["id"], space_code="Z1", area_sqm=200,
                            space_type="COMMON")
        janitor = create_vendor(
            name="CleanCo", trade="JANITORIAL", hourly_rate=40.00,
            sla_response_minutes=120, sla_resolve_minutes=480,
        )
        shift = create_shift(
            building["id"], janitor["id"], zone["id"], service_type="JANITORIAL",
            start_at="2026-05-05T08:00:00Z", end_at="2026-05-05T16:00:00Z",
            planned_headcount=3,
        )

    report_failure(asset["id"])
    return {
        "building": read_building(building["id"]),
        "asset": read_asset(asset["id"]),
        "pm_plan": plan,
        "zone": zone,
        "janitorial_vendor": janitor,
        "shift": shift,
    }


def setup_restricted_building(clock="2026-05-04T09:00:00Z") -> dict:
    """Two open P1 work orders tip the building from OPEN into RESTRICTED."""
    if clock:
        set_clock(clock)
    building = create_building()
    first = create_work_order(building["id"], priority="P1", wo_type="CORRECTIVE",
                              estimated_labor_hours=1, estimated_parts_cost=0)
    posture_at_one = read_building(building["id"])["operating_posture"]
    second = create_work_order(building["id"], priority="P1", wo_type="CORRECTIVE",
                               estimated_labor_hours=1, estimated_parts_cost=0)
    return {
        "building": read_building(building["id"]),
        "posture_at_one_open_p1": posture_at_one,
        "first_p1": first,
        "second_p1": second,
    }


# ---------------------------------------------------------------------------
# Tier 4: vendor standing — driving a vendor up the strike ladder
# ---------------------------------------------------------------------------
def strike_vendor_via_missed_shifts(building_id, zone_space_id, vendor_id,
                                    service_type, count, day="2026-04-01") -> dict:
    """Schedule `count` back-to-back shifts entirely in the past and let the epoch
    run sweep them into MISSED — each miss adds one strike to the vendor.

    The shifts are laid out end-to-end (08:00-10:00, 10:00-12:00, …) so the
    half-open vendor-overlap rule accepts all of them.
    """
    shifts = []
    for i in range(count):
        start_hour = 8 + 2 * i
        shifts.append(
            create_shift(
                building_id, vendor_id, zone_space_id,
                service_type=service_type,
                start_at=f"{day}T{start_hour:02d}:00:00Z",
                end_at=f"{day}T{start_hour + 2:02d}:00:00Z",
                planned_headcount=2,
            )
        )
    return {"shifts": shifts}


def setup_suspended_vendor_via_missed_shifts(clock_after="2026-05-04T09:00:00Z",
                                             suspended_hourly_rate=50.00,
                                             with_probation_vendor=True) -> dict:
    """A janitorial vendor with three MISSED shifts sits on 3 strikes → SUSPENDED.
    Optionally a second vendor with two MISSED shifts sits on 2 strikes → PROBATION.

    The shifts are all scheduled in April 2026 and the epoch run is executed while
    the logical clock still reads its startup value of 2026-05-01T00:00:00Z, which
    is already past every shift's end_at — so every one of them is swept to MISSED.
    """
    set_clock(CLOCK_STARTUP_DEFAULT)
    building = create_building()
    zone = create_space(building["id"], space_code="Z1", area_sqm=200,
                        space_type="COMMON")
    suspended = create_vendor(
        name="SuspCo", trade="JANITORIAL", hourly_rate=suspended_hourly_rate,
        sla_response_minutes=60, sla_resolve_minutes=240,
    )
    strike_vendor_via_missed_shifts(
        building["id"], zone["id"], suspended["id"], "JANITORIAL", 3, day="2026-04-01"
    )
    probation = None
    if with_probation_vendor:
        probation = create_vendor(
            name="ProbCo", trade="SECURITY", hourly_rate=50.00,
            sla_response_minutes=60, sla_resolve_minutes=240,
        )
        strike_vendor_via_missed_shifts(
            building["id"], zone["id"], probation["id"], "SECURITY", 2, day="2026-04-02"
        )
    run = ops_run(building["id"])
    if clock_after:
        set_clock(clock_after)
    return {
        "building": read_building(building["id"]),
        "zone": zone,
        "suspended_vendor": read_vendor(suspended["id"]),
        "probation_vendor": read_vendor(probation["id"]) if probation else None,
        "ops_run": run,
    }


def setup_vendor_on_two_strikes(clock="2026-05-04T09:00:00Z") -> dict:
    """Drive a vendor to PROBATION through two SLA-breached completions.

    Each cycle dispatches a P3 order, accepts it 90 minutes later (past the
    60-minute response window) and completes it — so each completion strikes the
    vendor once. The vendor's sla_resolve window (120 minutes) is still met.
    """
    set_clock(clock)
    building = create_building()
    vendor = create_vendor(
        name="SlowFix", trade="HVAC", hourly_rate=100.00,
        sla_response_minutes=60, sla_resolve_minutes=120,
    )
    breach_times = [
        ("2026-05-04T09:00:00Z", "2026-05-04T10:30:00Z", "2026-05-04T10:45:00Z"),
        ("2026-05-04T11:00:00Z", "2026-05-04T12:30:00Z", "2026-05-04T12:45:00Z"),
    ]
    work_orders = []
    for dispatched, accepted, completed in breach_times:
        set_clock(dispatched)
        work_order = create_work_order(
            building["id"], priority="P3", wo_type="CORRECTIVE",
            estimated_labor_hours=1, estimated_parts_cost=0,
        )
        dispatch = dispatch_work_order(work_order["id"], vendor["id"])
        set_clock(accepted)
        accept_dispatch(dispatch["id"], vendor["id"])
        set_clock(completed)
        complete_dispatch(dispatch["id"], vendor["id"], actual_labor_hours=1,
                          actual_parts_cost=0)
        work_orders.append(work_order)
    return {
        "building": read_building(building["id"]),
        "vendor": read_vendor(vendor["id"]),
        "work_orders": work_orders,
    }


def setup_vendor_with_four_completed_dispatches() -> dict:
    """One vendor, four COMPLETED dispatches. Only the OLDEST missed its response
    leg (accepted 120 minutes after a 60-minute window); the other three met both
    legs. Every dispatch resolves inside the 240-minute resolve window.

    The vendor therefore carries exactly one strike and stays ACTIVE, while the
    rolling and lifetime scores are computed over different subsets of the same rows.
    """
    set_clock("2026-05-04T09:00:00Z")
    building = create_building()
    vendor = create_vendor(
        name="CoolAir", trade="HVAC", hourly_rate=100.00,
        sla_response_minutes=60, sla_resolve_minutes=240,
    )

    # Dispatch A — accepted 120 minutes in (response breach), resolved in time.
    wo_a = create_work_order(building["id"], priority="P3", estimated_labor_hours=1,
                             estimated_parts_cost=0)
    d_a = dispatch_work_order(wo_a["id"], vendor["id"])
    set_clock("2026-05-04T11:00:00Z")
    accept_dispatch(d_a["id"], vendor["id"])
    set_clock("2026-05-04T12:00:00Z")
    complete_dispatch(d_a["id"], vendor["id"], actual_labor_hours=1, actual_parts_cost=0)

    # Dispatches B, C, D — accepted immediately, completed 30 minutes later.
    later = [
        ("2026-05-04T12:00:00Z", "2026-05-04T12:30:00Z"),
        ("2026-05-04T13:00:00Z", "2026-05-04T13:30:00Z"),
        ("2026-05-04T14:00:00Z", "2026-05-04T14:30:00Z"),
    ]
    work_orders = [wo_a]
    dispatches = [d_a]
    for dispatched_at, completed_at in later:
        set_clock(dispatched_at)
        work_order = create_work_order(building["id"], priority="P3",
                                       estimated_labor_hours=1, estimated_parts_cost=0)
        dispatch = dispatch_work_order(work_order["id"], vendor["id"])
        accept_dispatch(dispatch["id"], vendor["id"])
        set_clock(completed_at)
        complete_dispatch(dispatch["id"], vendor["id"], actual_labor_hours=1,
                          actual_parts_cost=0)
        work_orders.append(work_order)
        dispatches.append(dispatch)

    return {
        "building": building,
        "vendor": read_vendor(vendor["id"]),
        "work_orders": work_orders,
        "dispatches": dispatches,
        "breached_dispatch": d_a,
    }


def setup_vendor_at_third_strike_with_pending_offer() -> dict:
    """Extends setup_vendor_on_two_strikes (a PROBATION vendor on 2 strikes) with:

    - a third work order dispatched at 13:00 and accepted at 14:30, past the
      60-minute response window — so completing it will be the third strike;
    - a fourth work order dispatched to the same PROBATION vendor whose dispatch
      is still sitting in OFFERED, waiting to be swept up by the suspension.

    The clock is left at 14:40, inside the third order's 120-minute resolve window.
    """
    ctx = setup_vendor_on_two_strikes()
    building, vendor = ctx["building"], ctx["vendor"]

    set_clock("2026-05-04T13:00:00Z")
    third = create_work_order(building["id"], priority="P3", estimated_labor_hours=1,
                              estimated_parts_cost=0)
    third_dispatch = dispatch_work_order(third["id"], vendor["id"])
    set_clock("2026-05-04T14:30:00Z")
    accept_dispatch(third_dispatch["id"], vendor["id"])

    pending = create_work_order(building["id"], priority="P3", estimated_labor_hours=1,
                                estimated_parts_cost=0)
    pending_dispatch = dispatch_work_order(pending["id"], vendor["id"])
    set_clock("2026-05-04T14:40:00Z")

    return {
        "building": building,
        "vendor": read_vendor(vendor["id"]),
        "third_work_order": read_work_order(third["id"]),
        "third_dispatch": read_dispatch(third_dispatch["id"]),
        "pending_work_order": read_work_order(pending["id"]),
        "pending_dispatch": read_dispatch(pending_dispatch["id"]),
    }


def setup_overdue_pm_plan(next_due_at="2026-05-10T00:00:00Z", grace_days=5,
                          interval_days=30, clock="2026-05-16T09:00:00Z") -> dict:
    """One STANDARD asset with an ACTIVE plan whose grace window the clock has
    passed, so its freshly computed compliance_state is OVERDUE."""
    building = create_building()
    asset = create_asset(building["id"], asset_tag="AHU-01", category="HVAC",
                         criticality="STANDARD")
    plan = create_pm_plan(asset["id"], interval_days=interval_days,
                          grace_days=grace_days, next_due_at=next_due_at)
    if clock:
        set_clock(clock)
    return {"building": building, "asset": asset, "pm_plan": plan}


def setup_retired_asset(clock="2026-05-04T09:00:00Z", runtime_hours=16000) -> dict:
    """A STANDARD asset worn down to a condition_score below 20, reported failed and
    then swept into RETIRED by the epoch run. Its PM plan retires with it, and the
    building never froze because the asset is not CRITICAL."""
    if clock:
        set_clock(clock)
    building = create_building()
    asset = create_asset(building["id"], asset_tag="AHU-OLD", category="HVAC",
                         criticality="STANDARD", runtime_hours=runtime_hours)
    plan = create_pm_plan(asset["id"], next_due_at="2026-06-01T00:00:00Z")
    asset_after_failure = report_failure(asset["id"])
    run = ops_run(building["id"])
    return {
        "building": read_building(building["id"]),
        "asset": read_asset(asset["id"]),
        "asset_before_ops_run": asset_after_failure,
        "pm_plan": read_pm_plan(asset["id"], plan["id"]),
        "ops_run": run,
    }


def setup_in_progress_shift_then_freeze() -> dict:
    """A janitorial shift running 09:00–17:00 that the epoch run has already moved
    to IN_PROGRESS, after which a CRITICAL asset fails and freezes the building.

    The shift survives the freeze because the freeze cancels SCHEDULED shifts only,
    so the vendor is still occupied by it — which lets a later shift request violate
    the posture gate and the vendor-overlap rule at the same time.
    """
    set_clock("2026-05-04T09:00:00Z")
    building = create_building()
    zone = create_space(building["id"], space_code="Z1", area_sqm=200,
                        space_type="COMMON")
    janitor = create_vendor(
        name="CleanCo", trade="JANITORIAL", hourly_rate=40.00,
        sla_response_minutes=120, sla_resolve_minutes=480,
    )
    shift = create_shift(
        building["id"], janitor["id"], zone["id"], service_type="JANITORIAL",
        start_at="2026-05-05T09:00:00Z", end_at="2026-05-05T17:00:00Z",
        planned_headcount=3,
    )
    asset = create_asset(building["id"], asset_tag="CHILLER-01", category="HVAC",
                         criticality="CRITICAL")
    set_clock("2026-05-05T10:00:00Z")
    ops_run(building["id"])
    report_failure(asset["id"])
    return {
        "building": read_building(building["id"]),
        "zone": zone,
        "janitorial_vendor": janitor,
        "shift": get_success_data(api_client.get_shift(shift["id"], FM)),
        "asset": read_asset(asset["id"]),
    }


def setup_two_janitorial_vendors_with_shift() -> dict:
    """Two janitorial vendors; one SCHEDULED shift belonging to the first."""
    set_clock("2026-05-04T09:00:00Z")
    building = create_building()
    zone = create_space(building["id"], space_code="Z1", area_sqm=200,
                        space_type="COMMON")
    owner = create_vendor(name="CleanCo", trade="JANITORIAL", hourly_rate=40.00,
                          sla_response_minutes=120, sla_resolve_minutes=480)
    stranger = create_vendor(name="OtherCo", trade="JANITORIAL", hourly_rate=45.00,
                             sla_response_minutes=120, sla_resolve_minutes=480)
    shift = create_shift(
        building["id"], owner["id"], zone["id"], service_type="JANITORIAL",
        start_at="2026-05-06T08:00:00Z", end_at="2026-05-06T16:00:00Z",
        planned_headcount=3,
    )
    return {
        "building": building,
        "zone": zone,
        "owner_vendor": owner,
        "other_vendor": stranger,
        "shift": shift,
    }


def setup_two_leases_with_issued_statement() -> dict:
    """Two ACTIVE leases in one building; the first holds an ISSUED statement."""
    set_clock("2026-05-15T09:00:00Z")
    building = create_building()
    space_one = create_space(building["id"], space_code="S1", floor=1, area_sqm=100,
                             space_type="OFFICE")
    space_two = create_space(building["id"], space_code="S2", floor=2, area_sqm=100,
                             space_type="OFFICE")

    lease_one = create_lease(building["id"], tenant_name="Acme")
    create_allocation(lease_one["id"], space_one["id"], share_pct=100)
    activate_lease(lease_one["id"])

    lease_two = create_lease(building["id"], tenant_name="Bravo")
    create_allocation(lease_two["id"], space_two["id"], share_pct=100)
    activate_lease(lease_two["id"])

    statement = create_statement(lease_one["id"])
    issue_statement(statement["id"])
    return {
        "building": building,
        "billed_lease": read_lease(lease_one["id"]),
        "other_lease": read_lease(lease_two["id"]),
        "statement": read_statement(statement["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 5: leases, allocations, statements
# ---------------------------------------------------------------------------
def setup_active_lease(clock="2026-05-15T09:00:00Z", gross_area_sqm=1000,
                       space_area_sqm=100, share_pct=100,
                       base_rate_per_sqm_month=10.00,
                       lease_overrides=None, allocation_overrides=None) -> dict:
    """Building + one space + one lease holding a share of it, ACTIVE."""
    if clock:
        set_clock(clock)
    building = create_building(gross_area_sqm=gross_area_sqm)
    space = create_space(building["id"], space_code="S1", area_sqm=space_area_sqm,
                         space_type="OFFICE")
    lease = create_lease(
        building["id"], base_rate_per_sqm_month=base_rate_per_sqm_month,
        **(lease_overrides or {}),
    )
    allocation = create_allocation(
        lease["id"], space["id"], share_pct=share_pct, **(allocation_overrides or {})
    )
    activate_lease(lease["id"])
    return {
        "building": building,
        "space": read_space(space["id"]),
        "lease": read_lease(lease["id"]),
        "allocation": allocation,
    }


def setup_lease_over_two_spaces(clock="2026-05-15T09:00:00Z", gross_area_sqm=3000,
                                space_area_sqm=100,
                                base_rate_per_sqm_month=10.00) -> dict:
    """One lease taking 100% of two equal spaces in a building whose gross area is
    much larger than both — the geometry that makes a per-line utility pro-rata
    land on a repeating fraction."""
    if clock:
        set_clock(clock)
    building = create_building(gross_area_sqm=gross_area_sqm)
    space_one = create_space(building["id"], space_code="S1", floor=1,
                             area_sqm=space_area_sqm, space_type="OFFICE")
    space_two = create_space(building["id"], space_code="S2", floor=2,
                             area_sqm=space_area_sqm, space_type="OFFICE")
    lease = create_lease(building["id"], base_rate_per_sqm_month=base_rate_per_sqm_month)
    create_allocation(lease["id"], space_one["id"], share_pct=100)
    create_allocation(lease["id"], space_two["id"], share_pct=100)
    activate_lease(lease["id"])
    return {
        "building": building,
        "space_one": space_one,
        "space_two": space_two,
        "lease": read_lease(lease["id"]),
    }


def create_statement(lease_id, period_start="2026-05-01T00:00:00Z",
                     period_end="2026-05-31T23:59:59Z") -> dict:
    """Draft a statement with a freshly-read expected_lease_version — statement
    creation itself bumps the lease version, so it must be re-read every time."""
    version = read_lease_version(lease_id)
    return get_success_data(
        api_client.create_statement(
            lease_id, statement_payload(period_start, period_end, version), FC
        )
    )


def issue_statement(statement_id) -> dict:
    return get_success_data(api_client.issue_statement(statement_id, FC))


def dispute_statement(statement_id, lease_id, reason) -> dict:
    return get_success_data(
        api_client.dispute_statement(
            statement_id, {"dispute_reason": reason}, make_tenant_rep_headers(lease_id)
        )
    )


def settle_statement(statement_id) -> dict:
    return get_success_data(api_client.settle_statement(statement_id, FC))


def setup_disputed_statement_with_extra_reading() -> dict:
    """The two-space lease of setup_lease_over_two_spaces, billed for May 2026,
    ISSUED and then DISPUTED by the tenant, after which a second utility reading
    is appended — so a re-issue must recompute the money lines from current data.
    """
    ctx = setup_lease_over_two_spaces()
    create_utility_reading(
        ctx["building"]["id"], meter_type="ELECTRIC",
        period_start="2026-05-01T00:00:00Z", period_end="2026-05-15T23:59:59Z",
        consumption_kwh=4000, cost=1000.00,
    )
    statement = create_statement(ctx["lease"]["id"])
    issue_statement(statement["id"])
    dispute_statement(statement["id"], ctx["lease"]["id"],
                      "Utility pro-rata looks wrong")
    create_utility_reading(
        ctx["building"]["id"], meter_type="ELECTRIC",
        period_start="2026-05-16T00:00:00Z", period_end="2026-05-31T23:59:59Z",
        consumption_kwh=2000, cost=500.00,
    )
    ctx["statement"] = read_statement(statement["id"])
    return ctx


def setup_lease_with_collectable_work_order(clock="2026-05-10T09:00:00Z") -> dict:
    """An ACTIVE lease holding 100% of a 100 sqm space in a 1000 sqm building, plus
    one chargeable CORRECTIVE order closed inside May 2026 with a settled
    billable_amount of 200.00 — the order a May statement must collect."""
    ctx = setup_active_lease(clock=clock, gross_area_sqm=1000, space_area_sqm=100)
    vendor = create_vendor()
    work_order = create_work_order(
        ctx["building"]["id"], wo_type="CORRECTIVE", priority="P3",
        estimated_labor_hours=2, estimated_parts_cost=0, chargeable=True,
    )
    dispatch = dispatch_work_order(work_order["id"], vendor["id"])
    accept_dispatch(dispatch["id"], vendor["id"])
    set_clock("2026-05-10T11:00:00Z")
    complete_dispatch(dispatch["id"], vendor["id"], actual_labor_hours=2,
                      actual_parts_cost=0)
    qa_work_order(work_order["id"], "PASS")
    ctx["vendor"] = vendor
    ctx["work_order"] = read_work_order(work_order["id"])
    ctx["dispatch"] = read_dispatch(dispatch["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 6: capital projects and the funding ledger
# ---------------------------------------------------------------------------
def propose_capital_project(building_id, proposer_id=FC_PROPOSER_ID, **overrides) -> dict:
    return get_success_data(
        api_client.create_capital_project(
            capital_project_payload(building_id, **overrides),
            make_finance_controller_headers(proposer_id),
        )
    )


def decide_capital_project(project_id, decision="APPROVE",
                           decider_id=FC_APPROVER_ID) -> dict:
    """The decider must not be the proposer — segregation of duties."""
    return get_success_data(
        api_client.approve_capital_project(
            project_id, {"decision": decision},
            make_finance_controller_headers(decider_id),
        )
    )


def setup_approved_project(clock="2026-05-04T09:00:00Z", base_cost=1000.00,
                           building_id=None) -> dict:
    """A capital project proposed by fc-1 and APPROVED by fc-2, so its budget is
    drawable by work orders."""
    if clock:
        set_clock(clock)
    if building_id is None:
        building = create_building()
        building_id = building["id"]
    else:
        building = read_building(building_id)
    project = propose_capital_project(building_id, base_cost=base_cost)
    decide_capital_project(project["id"], "APPROVE")
    return {
        "building": building,
        "project": read_capital_project(project["id"]),
        "project_at_create": project,
    }


def setup_project_with_funded_order(clock="2026-05-04T09:00:00Z", base_cost=1000.00,
                                    estimated_labor_hours=5,
                                    estimated_parts_cost=0) -> dict:
    """An APPROVED project pulled into IN_FLIGHT by one funded P3 work order."""
    ctx = setup_approved_project(clock=clock, base_cost=base_cost)
    work_order = create_work_order(
        ctx["building"]["id"], wo_type="CORRECTIVE", priority="P3",
        estimated_labor_hours=estimated_labor_hours,
        estimated_parts_cost=estimated_parts_cost,
        funding_project_id=ctx["project"]["id"],
    )
    ctx["work_order"] = work_order
    ctx["project"] = read_capital_project(ctx["project"]["id"])
    return ctx
