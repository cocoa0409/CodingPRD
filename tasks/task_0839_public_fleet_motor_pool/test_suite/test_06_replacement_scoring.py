"""Replacement scoring threshold, work-order-completion flagging, and parallel status axes."""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    create_policy, set_clock, create_pool_vehicle, create_shop_bay, get_vehicle,
    create_fuel_log_payload, create_work_order_payload, TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
TECH = TEST_USERS["shop_tech_headers"]


def _evaluate_after_odometer(api, odometer, vin):
    """Old vehicle at clock 2026-06-01; push odometer via fuel log then evaluate."""
    create_policy()
    set_clock("2026-06-01T00:00:00Z")
    vehicle = create_pool_vehicle(vin=vin, in_service_date="2010-01-01T00:00:00Z",
                                  acquisition_cost_cents=2000000)
    get_success_data(api.create_fuel_log(
        vehicle["id"],
        create_fuel_log_payload(reading_at="2026-06-01T06:00:00Z", gallons=1,
                                fuel_cost_cents=0, odometer_miles=odometer), TECH))
    return validate_success(api.evaluate_replacement(vehicle["id"], ADMIN), 200)


# ─── boundary_precision_check / replacement_score_threshold_inclusive ───

def test_replacement_score_exactly_70_flags_vehicle(api):
    """PRD §3.3: "A score of exactly 70.00 flags the vehicle; 69.99 does not." PRD §3.3:
    "applies the same ACTIVE → FLAGGED_FOR_REPLACEMENT flip when the score reaches 70.00
    and the vehicle is still ACTIVE."

    Design: Difficulty/boundary_precision_check/replacement_score_threshold_inclusive
    """
    vehicle = _evaluate_after_odometer(api, 150000, "VIN-BND-A")
    assert vehicle["replacement_score"] == pytest.approx(70.00, abs=0.001)
    assert vehicle["lifecycle_status"] == "FLAGGED_FOR_REPLACEMENT"


def test_replacement_score_below_70_stays_active(api):
    """PRD §3.3: "A score of exactly 70.00 flags the vehicle; 69.99 does not." A score of
    69.73 is below the inclusive threshold and leaves the vehicle ACTIVE.

    Design: Difficulty/boundary_precision_check/replacement_score_threshold_inclusive
    """
    vehicle = _evaluate_after_odometer(api, 149000, "VIN-BND-B")
    assert vehicle["replacement_score"] == pytest.approx(69.73, abs=0.001)
    assert vehicle["lifecycle_status"] == "ACTIVE"


# ─── transitive_cascade / workorder_complete_flags_replacement ───

def _setup_near_threshold_vehicle(api, vin):
    create_policy()
    set_clock("2026-06-01T00:00:00Z")
    vehicle = create_pool_vehicle(vin=vin, in_service_date="2010-01-01T00:00:00Z",
                                  acquisition_cost_cents=2000000)
    get_success_data(api.create_fuel_log(
        vehicle["id"],
        create_fuel_log_payload(reading_at="2026-06-01T06:00:00Z", gallons=1,
                                fuel_cost_cents=0, odometer_miles=149000), TECH))
    evaluated = validate_success(api.evaluate_replacement(vehicle["id"], ADMIN), 200)
    return vehicle, evaluated


def test_score_before_completion_is_below_threshold_and_active(api):
    """PRD §3.3: "A score of exactly 70.00 flags the vehicle; 69.99 does not." Before the
    repair completes, the vehicle scores 69.73 and remains ACTIVE.

    Design: Difficulty/transitive_cascade/workorder_complete_flags_replacement
    """
    _, evaluated = _setup_near_threshold_vehicle(api, "VIN-FLAG-B")
    assert evaluated["replacement_score"] == pytest.approx(69.73, abs=0.001)
    assert evaluated["lifecycle_status"] == "ACTIVE"


def test_completion_adds_maintenance_and_flags_for_replacement(api):
    """PRD §3.3: "the order's total_cost_cents is added to the vehicle's
    lifetime_maintenance_cents, the vehicle's cost_per_mile_cents is recomputed, and the
    replacement_score is recomputed against the current clock."
    PRD §3.3: "If that recomputed score is at least 70.00 and the vehicle's
    lifecycle_status is still ACTIVE, the vehicle is flagged, moving ACTIVE →
    FLAGGED_FOR_REPLACEMENT on the lifecycle axis."

    Design: Difficulty/transitive_cascade/workorder_complete_flags_replacement
    """
    vehicle, _ = _setup_near_threshold_vehicle(api, "VIN-FLAG-A")
    bay = create_shop_bay(name="Bay-FLAG")
    wo = validate_success(api.create_work_order(create_work_order_payload(
        vehicle["id"], bay["id"], scheduled_start="2026-06-02T09:00:00Z",
        scheduled_end="2026-06-02T11:00:00Z", labor_rate_cents=20000), TECH), 201)
    validate_success(api.start_work_order(wo["id"], TECH), 200)
    validate_success(api.complete_work_order(wo["id"], {"labor_hours": 1, "parts_cost_cents": 0}, TECH), 200)
    after = get_vehicle(vehicle["id"])
    assert after["lifetime_maintenance_cents"] == 20000
    assert after["replacement_score"] == pytest.approx(70.23, abs=0.001)
    assert after["lifecycle_status"] == "FLAGGED_FOR_REPLACEMENT"


# ─── non_linear_state_machine / vehicle_parallel_operational_and_lifecycle_axes ───

def test_operational_axis_cycles_without_changing_lifecycle(api):
    """PRD §2.9: "A vehicle can be IN_SHOP while still ACTIVE, or OUT_OF_SERVICE while
    FLAGGED_FOR_REPLACEMENT; the axes move on their own triggers."
    PRD §3.3: "starting drives SCHEDULED → IN_PROGRESS and moves the vehicle's
    operational_status to IN_SHOP."
    PRD §3.3: "the vehicle's operational_status returns to IN_SERVICE".

    Design: Difficulty/non_linear_state_machine/vehicle_parallel_operational_and_lifecycle_axes
    """
    create_policy()
    set_clock("2026-06-01T00:00:00Z")
    vehicle = create_pool_vehicle(vin="VIN-PAR-1", in_service_date="2010-01-01T00:00:00Z",
                                  acquisition_cost_cents=2000000)
    bay = create_shop_bay(name="Bay-PAR")
    wo = validate_success(api.create_work_order(create_work_order_payload(
        vehicle["id"], bay["id"], wo_type="PM", scheduled_start="2026-06-02T09:00:00Z",
        scheduled_end="2026-06-02T11:00:00Z", labor_rate_cents=100), TECH), 201)
    validate_success(api.start_work_order(wo["id"], TECH), 200)
    in_shop = get_vehicle(vehicle["id"])
    assert in_shop["operational_status"] == "IN_SHOP"
    assert in_shop["lifecycle_status"] == "ACTIVE"
    validate_success(api.complete_work_order(wo["id"], {"labor_hours": 0, "parts_cost_cents": 0}, TECH), 200)
    back = get_vehicle(vehicle["id"])
    assert back["operational_status"] == "IN_SERVICE"
    assert back["lifecycle_status"] == "ACTIVE"


def test_lifecycle_flags_while_operational_stays_in_service(api):
    """PRD §2.9: "A vehicle can be IN_SHOP while still ACTIVE, or OUT_OF_SERVICE while
    FLAGGED_FOR_REPLACEMENT; the axes move on their own triggers."
    PRD §3.3: "A FleetAdmin can also force this recomputation directly through the
    replacement-evaluation action, which recomputes replacement_score against the current
    clock and applies the same ACTIVE → FLAGGED_FOR_REPLACEMENT flip when the score
    reaches 70.00 and the vehicle is still ACTIVE."

    Design: Difficulty/non_linear_state_machine/vehicle_parallel_operational_and_lifecycle_axes
    """
    vehicle = _evaluate_after_odometer(api, 150000, "VIN-PAR-2")
    assert vehicle["lifecycle_status"] == "FLAGGED_FOR_REPLACEMENT"
    assert vehicle["operational_status"] == "IN_SERVICE"
