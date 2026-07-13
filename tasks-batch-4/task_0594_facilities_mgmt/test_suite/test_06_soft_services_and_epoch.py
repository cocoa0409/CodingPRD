"""Soft-service coordination and the operational epoch: the half-open vendor interval,
preventive-maintenance promotion, asset retirement, and lease expiry.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_asset,
    assert_ops_run_result,
    assert_pm_plan,
    assert_space,
    create_building,
    create_space,
    create_vendor,
    ops_run,
    read_pm_plan,
    read_space,
    set_clock,
    setup_active_lease,
    setup_overdue_pm_plan,
    setup_retired_asset,
    shift_payload,
    validate_error,
    validate_paginated,
    validate_success,
    work_order_payload,
)

FM = TEST_USERS["facility_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]


# ---------------------------------------------------------------------------
# The half-open shift interval protects the vendor, not the space
# ---------------------------------------------------------------------------
def _two_buildings_with_one_janitor():
    set_clock("2026-05-04T09:00:00Z")
    building_one = create_building(name="Tower One", code="BLD-1")
    building_two = create_building(name="Tower Two", code="BLD-2")
    zone_one = create_space(building_one["id"], space_code="Z1", area_sqm=200,
                            space_type="COMMON")
    zone_two = create_space(building_two["id"], space_code="Z2", area_sqm=200,
                            space_type="COMMON")
    janitor = create_vendor(name="CleanCo", trade="JANITORIAL", hourly_rate=40.00,
                            sla_response_minutes=120, sla_resolve_minutes=480)
    return building_one, building_two, zone_one, zone_two, janitor


def test_a_shift_starting_when_another_ends_does_not_collide(api):
    """PRD §3.7: "The interval is **half-open**: it includes its start instant and
    excludes its end instant. A new shift that begins at exactly the instant an existing
    shift of the same vendor ends therefore does *not* collide, and both may stand."

    Design: Difficulty/resource_temporal_overlap/vendor_shift_half_open_interval_adjacent_ok_overlap_rejected
    """
    building_one, building_two, zone_one, zone_two, janitor = (
        _two_buildings_with_one_janitor()
    )
    validate_success(
        api.create_shift(
            shift_payload(building_one["id"], janitor["id"], zone_one["id"],
                          service_type="JANITORIAL",
                          start_at="2026-05-06T10:00:00Z",
                          end_at="2026-05-06T12:00:00Z", planned_headcount=3),
            FM,
        ),
        201,
    )

    adjacent = api.create_shift(
        shift_payload(building_two["id"], janitor["id"], zone_two["id"],
                      service_type="JANITORIAL",
                      start_at="2026-05-06T12:00:00Z",
                      end_at="2026-05-06T14:00:00Z", planned_headcount=3),
        FM,
    )
    data = validate_success(adjacent, 201)
    assert data["status"] == "SCHEDULED", (
        "touching endpoints do not collide under half-open semantics"
    )


def test_an_overlapping_shift_for_the_same_vendor_is_refused_across_buildings(api):
    """PRD §3.7: "And a crew cannot be in two places at once: a new shift whose interval
    intersects an existing shift of the *same* vendor that is `SCHEDULED` or
    `IN_PROGRESS` is refused with `ERR_SHIFT_OVERLAP` (HTTP 409), and the check ignores
    building, zone, and service line entirely — the resource being protected is the
    vendor, not the space."

    Design: Difficulty/resource_temporal_overlap/vendor_shift_half_open_interval_adjacent_ok_overlap_rejected
    """
    building_one, building_two, zone_one, zone_two, janitor = (
        _two_buildings_with_one_janitor()
    )
    validate_success(
        api.create_shift(
            shift_payload(building_one["id"], janitor["id"], zone_one["id"],
                          service_type="JANITORIAL",
                          start_at="2026-05-06T10:00:00Z",
                          end_at="2026-05-06T12:00:00Z", planned_headcount=3),
            FM,
        ),
        201,
    )
    validate_success(
        api.create_shift(
            shift_payload(building_two["id"], janitor["id"], zone_two["id"],
                          service_type="JANITORIAL",
                          start_at="2026-05-06T12:00:00Z",
                          end_at="2026-05-06T14:00:00Z", planned_headcount=3),
            FM,
        ),
        201,
    )

    # 11:59 intersects the first shift by one minute, in a different building.
    overlapping = api.create_shift(
        shift_payload(building_two["id"], janitor["id"], zone_two["id"],
                      service_type="JANITORIAL",
                      start_at="2026-05-06T11:59:00Z",
                      end_at="2026-05-06T13:00:00Z", planned_headcount=3),
        FM,
    )
    validate_error(overlapping, ApiErrorId.ERR_SHIFT_OVERLAP.value)
    assert overlapping.status_code == 409

    _, meta = validate_paginated(
        api.list_shifts(FM, params={"vendor_id": janitor["id"]})
    )
    assert meta["total_count"] == 2, "the refused shift must not have been created"


# ---------------------------------------------------------------------------
# The operational epoch
# ---------------------------------------------------------------------------
def test_epoch_run_promotes_an_overdue_plan_exactly_once(api):
    """PRD §3.1: "If the clock has reached or passed `next_due_at` but has not passed
    `next_due_at` advanced by `grace_days` days, the plan is `DUE` — both ends of that
    grace window are inclusive, so the instant exactly equal to `next_due_at` is already
    `DUE`, and the instant exactly equal to the end of the grace window is still `DUE`.
    Beyond that, the plan is `OVERDUE`."
    PRD §3.8: "The gathered plans are processed in ascending `next_due_at`, with
    `created_at` ascending as the tie-break, and each one produces a new work order in
    the building on the plan's asset, carrying the plan's identifier, with `wo_type`
    `PREVENTIVE`, `priority` `P2`, `chargeable` true, `estimated_labor_hours` of 3,
    `estimated_parts_cost` of 200.00, no funding project, and `status` `NEW`; the
    provisional costing variant then prices it."
    PRD §3.8: "Because a plan that already has an open preventive order is skipped,
    running the epoch twice in the same epoch produces the promotions only once. The
    identifiers of the new orders come back as `created_work_order_ids`."

    Design: Corner/state_machines/ops_run_promotes_overdue_pm_plan_into_preventive_work_order
    """
    ctx = setup_overdue_pm_plan(next_due_at="2026-05-10T00:00:00Z", grace_days=5,
                               interval_days=30, clock="2026-05-16T09:00:00Z")

    first_run = validate_success(api.ops_run(ctx["building"]["id"], FM))
    assert_ops_run_result(first_run)
    assert len(first_run["created_work_order_ids"]) == 1

    promoted, meta = validate_paginated(
        api.list_work_orders(FM, params={"pm_plan_id": ctx["pm_plan"]["id"]})
    )
    assert meta["total_count"] == 1
    order = promoted[0]
    assert order["wo_type"] == "PREVENTIVE"
    assert order["priority"] == "P2"
    assert order["status"] == "NEW"
    assert order["asset_id"] == ctx["asset"]["id"]
    # 3h * 80.00 = 240.00 labour, + 10% P2 = 24.00, + 200.00 * 1.15 = 230.00 parts.
    assert order["estimated_amount"] == pytest.approx(494.00, abs=0.01)

    second_run = validate_success(api.ops_run(ctx["building"]["id"], FM))
    assert second_run["created_work_order_ids"] == [], (
        "a plan that already has an open preventive order is skipped"
    )


def test_epoch_run_retires_a_dead_asset_and_its_plans(api):
    """PRD §3.8: "**Third, asset retirement.** An asset that is `OUT_OF_SERVICE` and
    whose `condition_score` has fallen below 20 moves `OUT_OF_SERVICE → RETIRED`; its
    identifier comes back in `retired_asset_ids`. Retiring the asset retires every plan
    of that asset that is `ACTIVE` or `SUSPENDED`."
    PRD §3.1: "Start from 100. Subtract 5 points for each *complete* block of 1000
    runtime hours the asset has accumulated — 999 hours cost nothing, 1000 hours cost 5,
    1999 hours still cost 5, 2000 hours cost 10 — and subtract a further 12 points for
    every failure in `failure_count`."

    Design: Corner/state_machines/ops_run_retires_dead_asset_and_its_pm_plans
    """
    ctx = setup_retired_asset(clock="2026-05-04T09:00:00Z", runtime_hours=16000)

    # 16 complete blocks cost 80 points; the single failure costs 12 more.
    assert ctx["asset_before_ops_run"]["condition_score"] == pytest.approx(8.00, abs=0.01)
    assert ctx["asset_before_ops_run"]["status"] == "OUT_OF_SERVICE"

    assert ctx["asset"]["id"] in ctx["ops_run"]["retired_asset_ids"]

    asset = validate_success(api.get_asset(ctx["asset"]["id"], FM))
    assert_asset(asset)
    assert asset["status"] == "RETIRED"

    plan = read_pm_plan(ctx["asset"]["id"], ctx["pm_plan"]["id"])
    assert_pm_plan(plan)
    assert plan["status"] == "RETIRED"

    building = validate_success(api.get_building(ctx["building"]["id"], FM))
    assert building["operating_posture"] == "OPEN", (
        "a STANDARD asset never counted towards oos_critical_asset_count"
    )


def test_epoch_run_expires_a_lapsed_lease_and_releases_its_allocations(api):
    """PRD §3.8: "**Fourth, lease expiry.** A lease that is `ACTIVE` and whose
    `end_date` the clock has strictly passed moves `ACTIVE → EXPIRED`; its identifier
    comes back in `expired_lease_ids`. Every allocation of that lease that is `ACTIVE`
    moves to `RELEASED`, and each affected space's `free_share_pct` rises back by
    exactly that allocation's `share_pct`."

    Design: Corner/state_machines/ops_run_expires_lease_and_releases_its_allocations
    """
    ctx = setup_active_lease(
        clock="2026-05-15T09:00:00Z", gross_area_sqm=1000, space_area_sqm=200,
        share_pct=100,
        lease_overrides={"start_date": "2026-05-01T00:00:00Z",
                         "end_date": "2026-05-31T23:59:59Z"},
        allocation_overrides={"effective_from": "2026-05-01T00:00:00Z",
                              "effective_to": "2026-05-31T23:59:59Z"},
    )
    set_clock("2026-06-01T00:00:01Z")

    run = validate_success(api.ops_run(ctx["building"]["id"], FM))
    assert_ops_run_result(run)
    assert ctx["lease"]["id"] in run["expired_lease_ids"]

    lease = validate_success(api.get_lease(ctx["lease"]["id"], FC))
    assert lease["status"] == "EXPIRED"
    assert lease["allocated_area_sqm"] == pytest.approx(0, abs=0.01)

    allocation = validate_success(
        api.get_allocation(ctx["allocation"]["id"], FC)
    )
    assert allocation["status"] == "RELEASED"

    space = read_space(ctx["space"]["id"])
    assert_space(space)
    assert space["allocated_share_pct"] == pytest.approx(0, abs=0.01)
    assert space["free_share_pct"] == pytest.approx(100, abs=0.01)
    assert space["occupancy_status"] == "VACANT"


def test_work_order_naming_a_retired_asset_is_refused(api):
    """PRD §3.4: "And an asset that has been retired can no longer take work: naming a
    `RETIRED` asset is refused with `ERR_ASSET_RETIRED`."

    Design: Corner/validations/work_order_on_retired_asset_rejected
    """
    ctx = setup_retired_asset(clock="2026-05-04T09:00:00Z", runtime_hours=16000)
    assert ctx["asset"]["status"] == "RETIRED"

    response = api.create_work_order(
        work_order_payload(ctx["building"]["id"], asset_id=ctx["asset"]["id"],
                           wo_type="CORRECTIVE", priority="P1",
                           estimated_labor_hours=2, estimated_parts_cost=0),
        FM,
    )
    validate_error(response, ApiErrorId.ERR_ASSET_RETIRED.value)
    assert response.status_code == 409
