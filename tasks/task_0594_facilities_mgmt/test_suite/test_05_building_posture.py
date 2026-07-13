"""Operating posture — the building-level gate. The freeze cascade from a critical
asset failure, the RESTRICTED count threshold, and the way posture decides which work
orders may be raised at all.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_asset,
    assert_building,
    assert_pm_plan,
    create_asset,
    create_building,
    read_building,
    read_pm_plan,
    read_vendor,
    set_clock,
    setup_frozen_building,
    setup_restricted_building,
    validate_error,
    validate_success,
    work_order_payload,
)

FM = TEST_USERS["facility_manager_headers"]


# ---------------------------------------------------------------------------
# The freeze cascade
# ---------------------------------------------------------------------------
def test_critical_asset_failure_freezes_the_building(api):
    """PRD §3.1: "When a `FacilityManager` or `PlatformAdmin` reports a failure, the
    asset moves `IN_SERVICE → OUT_OF_SERVICE`; reporting a failure on an asset that is
    not `IN_SERVICE` is refused with `ERR_ASSET_NOT_IN_SERVICE`."
    PRD §3.1: "If the failed asset was `CRITICAL`, that count reaches at least 1 and the
    building's posture becomes `FROZEN` — from either `OPEN` or `RESTRICTED`."
    PRD §2.8: "The derivation reads two counters that the building also exposes.
    `oos_critical_asset_count` is the number of assets in the building whose
    `criticality` is `CRITICAL` and whose `status` is `OUT_OF_SERVICE`; a `RETIRED`
    asset does not count towards it."

    Design: Difficulty/transitive_cascade/critical_asset_failure_freezes_building_suspends_plans_cancels_shifts
    """
    ctx = setup_frozen_building(clock="2026-05-04T09:00:00Z", with_pm_plan=True,
                                with_shift=True)

    asset = ctx["asset"]
    assert_asset(asset)
    assert asset["status"] == "OUT_OF_SERVICE"
    assert asset["failure_count"] == 1
    # A fresh asset has no runtime decay, so one failure costs exactly 12 points.
    assert asset["condition_score"] == pytest.approx(88.00, abs=0.01)

    building = ctx["building"]
    assert_building(building)
    assert building["oos_critical_asset_count"] == 1
    assert building["operating_posture"] == "FROZEN"


def test_freeze_suspends_plans_and_cancels_shifts_without_striking_the_vendor(api):
    """PRD §3.1: "Every preventive-maintenance plan on any asset of that building that
    is currently `ACTIVE` moves `ACTIVE → SUSPENDED`, and every soft-service shift of
    that building that is currently `SCHEDULED` moves `SCHEDULED → CANCELLED`."
    PRD §3.1: "Those shift cancellations are *not* the vendor's fault and carry no
    penalty of any kind against the vendor."
    PRD §3.7: "A shift cancelled by a building freeze, by contrast, is nobody's fault
    and costs the vendor nothing."

    Design: Difficulty/transitive_cascade/critical_asset_failure_freezes_building_suspends_plans_cancels_shifts
    """
    ctx = setup_frozen_building(clock="2026-05-04T09:00:00Z", with_pm_plan=True,
                                with_shift=True)

    plan = read_pm_plan(ctx["asset"]["id"], ctx["pm_plan"]["id"])
    assert_pm_plan(plan)
    assert plan["status"] == "SUSPENDED"

    shift = validate_success(api.get_shift(ctx["shift"]["id"], FM))
    assert shift["status"] == "CANCELLED"

    vendor = read_vendor(ctx["janitorial_vendor"]["id"])
    assert vendor["strike_count"] == 0, (
        "a posture cancellation carries no penalty against the vendor"
    )
    assert vendor["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# The RESTRICTED count threshold
# ---------------------------------------------------------------------------
def test_one_open_p1_leaves_the_building_open_and_two_restrict_it(api):
    """PRD §2.8: "From those two counters: if `oos_critical_asset_count` is at least 1,
    the posture is `FROZEN`; otherwise, if `open_p1_work_order_count` is at least 2, the
    posture is `RESTRICTED`; otherwise the posture is `OPEN`. A brand-new building with
    no assets and no work orders is therefore `OPEN`, and a building with exactly one
    open `P1` order is `OPEN` while a building with exactly two is `RESTRICTED`."

    Design: Difficulty/boundary_precision_check/restricted_posture_at_exactly_two_open_p1_orders
    """
    ctx = setup_restricted_building(clock="2026-05-04T09:00:00Z")

    assert ctx["posture_at_one_open_p1"] == "OPEN", (
        "one open P1 order is below the threshold of 2"
    )

    building = ctx["building"]
    assert_building(building)
    assert building["open_p1_work_order_count"] == 2
    assert building["operating_posture"] == "RESTRICTED"


def test_restricted_building_refuses_p3_but_admits_p2(api):
    """PRD §2.8: "While a building is `RESTRICTED`, a new work order of priority `P3` or
    `P4` is refused with `ERR_BUILDING_RESTRICTED` (HTTP 409), while `P1` and `P2`
    orders pass; soft-service scheduling is unaffected by `RESTRICTED`."

    Design: Difficulty/boundary_precision_check/restricted_posture_at_exactly_two_open_p1_orders
    """
    ctx = setup_restricted_building(clock="2026-05-04T09:00:00Z")
    building_id = ctx["building"]["id"]

    refused = api.create_work_order(
        work_order_payload(building_id, wo_type="CORRECTIVE", priority="P3",
                           estimated_labor_hours=1, estimated_parts_cost=0),
        FM,
    )
    validate_error(refused, ApiErrorId.ERR_BUILDING_RESTRICTED.value)
    assert refused.status_code == 409

    admitted = api.create_work_order(
        work_order_payload(building_id, wo_type="CORRECTIVE", priority="P2",
                           estimated_labor_hours=1, estimated_parts_cost=0),
        FM,
    )
    data = validate_success(admitted, 201)
    assert data["status"] == "NEW", "only P3 and P4 orders are gated by RESTRICTED"


# ---------------------------------------------------------------------------
# The posture gate on work-order creation
# ---------------------------------------------------------------------------
def test_frozen_building_refuses_a_preventive_p2_order(api):
    """PRD §2.8: "While a building is `FROZEN`, a new work order is refused with
    `ERR_BUILDING_FROZEN` (HTTP 409) unless it is both `CORRECTIVE` and priority `P1` —
    the crisis is only allowed to be fixed, not worked around — and scheduling any
    soft-service shift in that building is refused with `ERR_BUILDING_FROZEN` regardless
    of its service line."

    Design: Difficulty/cross_entity_state_dependency/work_order_creation_depends_on_building_posture
    """
    ctx = setup_frozen_building(clock="2026-05-04T09:00:00Z")
    assert ctx["building"]["operating_posture"] == "FROZEN"

    response = api.create_work_order(
        work_order_payload(ctx["building"]["id"], asset_id=ctx["asset"]["id"],
                           wo_type="PREVENTIVE", priority="P2",
                           estimated_labor_hours=2, estimated_parts_cost=0),
        FM,
    )
    validate_error(response, ApiErrorId.ERR_BUILDING_FROZEN.value)
    assert response.status_code == 409


def test_frozen_building_admits_the_corrective_p1_repair(api):
    """PRD §2.8: "While a building is `FROZEN`, a new work order is refused with
    `ERR_BUILDING_FROZEN` (HTTP 409) unless it is both `CORRECTIVE` and priority `P1` —
    the crisis is only allowed to be fixed, not worked around — and scheduling any
    soft-service shift in that building is refused with `ERR_BUILDING_FROZEN` regardless
    of its service line."
    PRD §2.8: "From those two counters: if `oos_critical_asset_count` is at least 1, the
    posture is `FROZEN`; otherwise, if `open_p1_work_order_count` is at least 2, the
    posture is `RESTRICTED`; otherwise the posture is `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/work_order_creation_depends_on_building_posture
    """
    ctx = setup_frozen_building(clock="2026-05-04T09:00:00Z")

    response = api.create_work_order(
        work_order_payload(ctx["building"]["id"], asset_id=ctx["asset"]["id"],
                           wo_type="CORRECTIVE", priority="P1",
                           estimated_labor_hours=2, estimated_parts_cost=0),
        FM,
    )
    data = validate_success(response, 201)
    assert data["status"] == "NEW"

    building = read_building(ctx["building"]["id"])
    assert building["operating_posture"] == "FROZEN", (
        "the out-of-service critical asset keeps the building frozen; one open P1 "
        "order does not change that"
    )


# ---------------------------------------------------------------------------
# The cascade is immediately visible
# ---------------------------------------------------------------------------
def test_posture_cascade_is_visible_without_any_lag(api):
    """PRD §3.1: "When a `FacilityManager` or `PlatformAdmin` reports a failure, the
    asset moves `IN_SERVICE → OUT_OF_SERVICE`; reporting a failure on an asset that is
    not `IN_SERVICE` is refused with `ERR_ASSET_NOT_IN_SERVICE`."
    PRD §2.8: "It is never set by a caller. It is derived, and it is recomputed from
    scratch after every asset failure report, every work-order creation, every
    quality-assurance decision, every work-order cancellation, and every operational
    epoch run."
    PRD §3.1: "If the failed asset was `CRITICAL`, that count reaches at least 1 and the
    building's posture becomes `FROZEN` — from either `OPEN` or `RESTRICTED`."

    Design: Corner/consistency_model/posture_cascade_visible_in_same_request_response
    """
    set_clock("2026-05-04T09:00:00Z")
    building = create_building()
    asset = create_asset(building["id"], asset_tag="CHILLER-01", category="HVAC",
                         criticality="CRITICAL")

    reported = validate_success(api.report_asset_failure(asset["id"], FM))
    assert reported["status"] == "OUT_OF_SERVICE", (
        "the mutating call's own response already carries the new state"
    )

    immediately_after = validate_success(api.get_building(building["id"], FM))
    assert immediately_after["operating_posture"] == "FROZEN"
    assert immediately_after["oos_critical_asset_count"] == 1
