"""The order in which a request is judged. Each test drives one request that violates
two rules at once and pins which of the two errors comes back — the earlier step in the
fixed sequence always wins.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    allocation_payload,
    create_allocation,
    create_building,
    create_lease,
    create_space,
    create_work_order,
    read_capital_project,
    read_space,
    read_work_order,
    set_clock,
    setup_approved_project,
    setup_in_progress_shift_then_freeze,
    setup_suspended_vendor_via_missed_shifts,
    shift_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

FM = TEST_USERS["facility_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]


# ---------------------------------------------------------------------------
# Step 11 (posture gate) beats step 15 (shift overlap)
# ---------------------------------------------------------------------------
def test_frozen_posture_is_reported_before_a_shift_overlap(api):
    """PRD §2.6: "Because a single request can violate several rules at once, the order of
    evaluation is fixed and the first failure wins."
    PRD §2.6: "11. **Building posture gate** — §2.8, else `ERR_BUILDING_FROZEN` or
    `ERR_BUILDING_RESTRICTED`."
    PRD §2.6: "15. **Shift overlap** — else `ERR_SHIFT_OVERLAP`."
    PRD §2.8: "While a building is `FROZEN`, a new work order is refused with
    `ERR_BUILDING_FROZEN` (HTTP 409) unless it is both `CORRECTIVE` and priority `P1` —
    the crisis is only allowed to be fixed, not worked around — and scheduling any
    soft-service shift in that building is refused with `ERR_BUILDING_FROZEN` regardless of
    its service line."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_beats_shift_overlap_state_vs_temporal
    """
    ctx = setup_in_progress_shift_then_freeze()
    assert ctx["building"]["operating_posture"] == "FROZEN"
    assert ctx["shift"]["status"] == "IN_PROGRESS"

    # 10:30–12:00 intersects the vendor's running 09:00–17:00 shift AND lands in a
    # FROZEN building. The posture gate is judged first.
    response = api.create_shift(
        shift_payload(ctx["building"]["id"], ctx["janitorial_vendor"]["id"],
                      ctx["zone"]["id"], service_type="JANITORIAL",
                      start_at="2026-05-05T10:30:00Z",
                      end_at="2026-05-05T12:00:00Z", planned_headcount=2),
        FM,
    )
    validate_error(response, ApiErrorId.ERR_BUILDING_FROZEN.value)
    assert response.status_code == 409


def test_the_refused_shift_leaves_the_running_shift_and_the_board_untouched(api):
    """PRD §3.1: "Every preventive-maintenance plan on any asset of that building that is
    currently `ACTIVE` moves `ACTIVE → SUSPENDED`, and every soft-service shift of that
    building that is currently `SCHEDULED` moves `SCHEDULED → CANCELLED`."
    PRD §3.8: "A `SCHEDULED` shift whose `start_at` has been reached or passed by the clock
    while the clock is still strictly before its `end_at` moves `SCHEDULED → IN_PROGRESS`,
    and its identifier comes back in `in_progress_shift_ids`."
    PRD §2.8: "While a building is `FROZEN`, a new work order is refused with
    `ERR_BUILDING_FROZEN` (HTTP 409) unless it is both `CORRECTIVE` and priority `P1` —
    the crisis is only allowed to be fixed, not worked around — and scheduling any
    soft-service shift in that building is refused with `ERR_BUILDING_FROZEN` regardless of
    its service line."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_beats_shift_overlap_state_vs_temporal
    """
    ctx = setup_in_progress_shift_then_freeze()

    refused = api.create_shift(
        shift_payload(ctx["building"]["id"], ctx["janitorial_vendor"]["id"],
                      ctx["zone"]["id"], service_type="JANITORIAL",
                      start_at="2026-05-05T10:30:00Z",
                      end_at="2026-05-05T12:00:00Z", planned_headcount=2),
        FM,
    )
    assert refused.status_code == 409

    running = validate_success(api.get_shift(ctx["shift"]["id"], FM))
    assert running["status"] == "IN_PROGRESS", (
        "the freeze cancels SCHEDULED shifts only, so the running one survives"
    )

    _, meta = validate_paginated(
        api.list_shifts(FM, params={"vendor_id": ctx["janitorial_vendor"]["id"]})
    )
    assert meta["total_count"] == 1, "the refused shift left no row behind"


# ---------------------------------------------------------------------------
# Step 12 (vendor eligibility) beats step 19 (capital funding)
# ---------------------------------------------------------------------------
def _suspended_vendor_and_funded_order():
    """A SUSPENDED janitorial vendor charging 500.00/hour, plus a P3 order funded by an
    APPROVED project that holds only 700.00 of remaining budget — so dispatching that
    vendor would both blow the budget and touch a suspended vendor."""
    ctx = setup_suspended_vendor_via_missed_shifts(
        clock_after="2026-05-04T09:00:00Z", suspended_hourly_rate=500.00,
        with_probation_vendor=False,
    )
    project_ctx = setup_approved_project(
        clock=None, base_cost=1000.00, building_id=ctx["building"]["id"]
    )
    work_order = create_work_order(
        ctx["building"]["id"], wo_type="CORRECTIVE", priority="P3",
        estimated_labor_hours=5, estimated_parts_cost=0,
        funding_project_id=project_ctx["project"]["id"],
    )
    return ctx, project_ctx, work_order


def test_vendor_suspension_is_reported_before_a_budget_overrun(api):
    """PRD §2.6: "Because a single request can violate several rules at once, the order of
    evaluation is fixed and the first failure wins."
    PRD §2.6: "12. **Vendor eligibility** — a suspended vendor may not be dispatched, else
    `ERR_VENDOR_SUSPENDED`."
    PRD §2.6: "19. **Capital funding** — else `ERR_PROJECT_BUDGET_EXCEEDED`."
    PRD §3.2: "A vendor in `ACTIVE` or `PROBATION` standing may be given new work; a
    `SUSPENDED` vendor may not, and any attempt to dispatch to one is refused with
    `ERR_VENDOR_SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/vendor_suspension_beats_project_budget_safety_vs_fiscal
    """
    ctx, project_ctx, work_order = _suspended_vendor_and_funded_order()
    suspended = ctx["suspended_vendor"]
    assert suspended["strike_count"] == 3
    assert suspended["status"] == "SUSPENDED"

    # Re-pricing at the vendor's 500.00/hour would need 5 * 500.00 = 2500.00, far past
    # the 700.00 remaining plus the 400.00 this order already holds.
    response = api.create_dispatch(
        work_order["id"],
        {"vendor_id": suspended["id"],
         "expected_work_order_version": work_order["version"]},
        FM,
    )
    validate_error(response, ApiErrorId.ERR_VENDOR_SUSPENDED.value)
    assert response.status_code == 409


def test_the_refused_dispatch_leaves_the_order_and_the_ledger_untouched(api):
    """PRD §3.3: "`committed_amount` is at all times the sum of `estimated_amount` across
    the work orders funded by the project whose `status` is `NEW`, `DISPATCHED`,
    `IN_PROGRESS`, or `PENDING_QA` — money promised but not yet spent."
    PRD §3.5: "Dispatching an order sends it to a vendor and moves it `NEW → DISPATCHED`."
    PRD §3.2: "A vendor in `ACTIVE` or `PROBATION` standing may be given new work; a
    `SUSPENDED` vendor may not, and any attempt to dispatch to one is refused with
    `ERR_VENDOR_SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/vendor_suspension_beats_project_budget_safety_vs_fiscal
    """
    ctx, project_ctx, work_order = _suspended_vendor_and_funded_order()

    refused = api.create_dispatch(
        work_order["id"],
        {"vendor_id": ctx["suspended_vendor"]["id"],
         "expected_work_order_version": work_order["version"]},
        FM,
    )
    assert refused.status_code == 409

    order = read_work_order(work_order["id"])
    assert order["status"] == "NEW"
    # Still on the house rate: 5h * 80.00 = 400.00.
    assert order["estimated_amount"] == pytest.approx(400.00, abs=0.01)

    project = read_capital_project(project_ctx["project"]["id"])
    assert project["committed_amount"] == pytest.approx(400.00, abs=0.01)
    assert project["remaining_amount"] == pytest.approx(700.00, abs=0.01)


# ---------------------------------------------------------------------------
# Step 14 (cross-aggregate coherence) beats step 17 (allocation capacity)
# ---------------------------------------------------------------------------
def _cross_building_allocation_target():
    """Building A holds a DRAFT lease. Building B holds a space that is already fully
    allocated to a different lease for the whole of 2026."""
    set_clock("2026-05-04T09:00:00Z")
    building_a = create_building(name="Tower A", code="BLD-A")
    building_b = create_building(name="Tower B", code="BLD-B")
    space_b = create_space(building_b["id"], space_code="SB", area_sqm=100,
                           space_type="OFFICE")
    lease_b = create_lease(building_b["id"], tenant_name="Bravo",
                           start_date="2026-01-01T00:00:00Z",
                           end_date="2026-12-31T23:59:59Z")
    create_allocation(lease_b["id"], space_b["id"], share_pct=100,
                      effective_from="2026-01-01T00:00:00Z",
                      effective_to="2026-12-31T23:59:59Z")
    lease_a = create_lease(building_a["id"], tenant_name="Alpha",
                           start_date="2026-01-01T00:00:00Z",
                           end_date="2026-12-31T23:59:59Z")
    return space_b, lease_a


def test_space_building_mismatch_is_reported_before_a_share_overrun(api):
    """PRD §2.6: "Because a single request can violate several rules at once, the order of
    evaluation is fixed and the first failure wins."
    PRD §2.6: "14. **Cross-aggregate coherence** — else `ERR_PM_PLAN_ASSET_MISMATCH`,
    `ERR_ASSET_BUILDING_MISMATCH`, or `ERR_SPACE_BUILDING_MISMATCH`."
    PRD §2.6: "17. **Allocation capacity** — else `ERR_SPACE_SHARE_EXCEEDED`."
    PRD §3.9: "The space must belong to the lease's own building, or the allocation is
    refused with `ERR_SPACE_BUILDING_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/space_building_mismatch_beats_share_exceeded_referential_vs_constraint
    """
    space_b, lease_a = _cross_building_allocation_target()

    # The space sits in the wrong building AND is already 100% allocated on those dates.
    response = api.create_allocation(
        lease_a["id"],
        allocation_payload(space_b["id"], share_pct=50,
                           effective_from="2026-06-01T00:00:00Z",
                           effective_to="2026-06-30T23:59:59Z"),
        FC,
    )
    validate_error(response, ApiErrorId.ERR_SPACE_BUILDING_MISMATCH.value)
    assert response.status_code == 422


def test_the_refused_allocation_leaves_the_space_fully_allocated(api):
    """PRD §3.9: "The capacity rule is aggregate, not exclusive. Two leases may hold
    shares of the same space over the same dates, provided the shares fit: for every date
    inside the new allocation's closed interval, the sum of `share_pct` across the space's
    `ACTIVE` allocations whose own closed intervals cover that date, plus the new
    `share_pct`, must not exceed 100. If it would exceed 100 on any single date, the
    request is refused with `ERR_SPACE_SHARE_EXCEEDED` (HTTP 422)."
    PRD §3.9: "The space must belong to the lease's own building, or the allocation is
    refused with `ERR_SPACE_BUILDING_MISMATCH`."
    PRD §2.10: "The first is space occupancy. For any space, `allocated_share_pct` and
    `free_share_pct` always sum to exactly 100, after every allocation and after every
    release."

    Design: Difficulty/priority_pair_validation_conflict/space_building_mismatch_beats_share_exceeded_referential_vs_constraint
    """
    space_b, lease_a = _cross_building_allocation_target()

    refused = api.create_allocation(
        lease_a["id"],
        allocation_payload(space_b["id"], share_pct=50,
                           effective_from="2026-06-01T00:00:00Z",
                           effective_to="2026-06-30T23:59:59Z"),
        FC,
    )
    assert refused.status_code == 422

    space = read_space(space_b["id"])
    assert space["allocated_share_pct"] == pytest.approx(100, abs=0.01)
    assert space["free_share_pct"] == pytest.approx(0, abs=0.01)

    allocations, meta = validate_paginated(
        api.list_allocations(FC, params={"space_id": space_b["id"]})
    )
    assert meta["total_count"] == 1, "the refused allocation created no row"
