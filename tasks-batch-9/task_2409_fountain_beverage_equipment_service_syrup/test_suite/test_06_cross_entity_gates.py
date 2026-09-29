"""Gates a resource inherits from a sibling entity's state.

A route stop cannot be served while a dispenser at the same outlet reads
OUT_OF_SPEC, and a dispenser cannot leave SERVICE_HOLD while one of its own
sanitation tasks sits in OVERDUE. Both gates lift once the sibling moves.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    activate_agreement,
    add_stop,
    add_telemetry,
    allocate,
    ApiErrorId,
    arrive_stop,
    complete_task,
    create_agreement,
    create_outlet,
    create_position,
    create_route,
    create_supply_item,
    create_task,
    create_unit,
    dispatch_route,
    evaluate_task,
    pin_clock,
    place_service_hold,
    read_outlet,
    read_position,
    read_route,
    read_stop,
    read_supply_item,
    read_task,
    read_unit,
    run_forecast,
    serve_stop,
    service_hold_payload,
    TEST_USERS,
)

DRIVER = TEST_USERS["driver_headers"]
TECH = TEST_USERS["technician_headers"]
OFFICER = TEST_USERS["officer_headers"]


def _arrived_stop_behind_an_out_of_spec_machine():
    """An ARRIVED stop holding 32 units at an outlet whose only machine reads 5.40."""
    pin_clock("2026-08-01T00:00:00Z")
    outlet = create_outlet(
        name="Speedway Mart 19",
        account_code="ACCT-CE-A",
        region_code="R13",
        throughput_tier="MEDIUM",
        water_hardness_gpg=10,
    )
    agreement = create_agreement(
        outlet["id"],
        annual_commitment_gallons=4000,
        equipment_value_cents=300000,
        free_on_loan=True,
        shortfall_fee_cents_per_gallon=40,
    )
    unit = create_unit(
        outlet["id"], agreement["id"], serial_number="SN-CE-A-01",
        installed_at="2026-02-01T00:00:00Z",
    )
    activate_agreement(agreement["id"])
    item = create_supply_item(
        sku_code="COKE_CART_CE",
        brand_name="Coca-Cola",
        supply_form="CARTRIDGE",
        case_pack_units=4,
        ounces_per_unit=350,
        promotional=False,
        national_allocation_units=1000,
    )
    add_telemetry(unit["id"], item["id"], 7000, "2026-07-31T00:00:00Z", window_days=7)
    position = create_position(outlet["id"], item["id"], 6)
    forecast = run_forecast(position["id"], "TRAILING_ACTUAL", 7)
    route = create_route(
        route_code="RT-CE-1",
        depot_region_code="R13",
        service_date="2026-08-02T00:00:00Z",
        van_code="V-61",
        capacity_units=500,
    )
    stop = add_stop(
        route["id"], outlet["id"], 1, "2026-08-02T08:00:00Z", "2026-08-02T10:00:00Z"
    )
    allocation = allocate(stop["id"], [position["id"]])
    failing = create_task(unit["id"], "BRIX_CALIBRATION", "2026-08-05T00:00:00Z")
    passing = create_task(unit["id"], "BRIX_CALIBRATION", "2026-08-06T00:00:00Z")
    graded = complete_task(failing["id"], TECH, measured_brix_ratio=5.40)
    dispatch_route(route["id"])
    arrive_stop(stop["id"])
    return {
        "unit": unit,
        "item": item,
        "position": position,
        "forecast": forecast,
        "route": route,
        "stop": stop,
        "allocation": allocation,
        "passing_task": passing,
        "graded": graded,
    }


def _held_unit_with_an_overdue_sanitation_task():
    """A unit on SERVICE_HOLD whose sanitation task has already gone OVERDUE."""
    pin_clock("2026-08-01T00:00:00Z")
    outlet = create_outlet(
        name="Rink Concession 2",
        account_code="ACCT-CE-B",
        region_code="R14",
        throughput_tier="MEDIUM",
        water_hardness_gpg=10,
    )
    agreement = create_agreement(
        outlet["id"],
        annual_commitment_gallons=4000,
        equipment_value_cents=300000,
        free_on_loan=True,
        shortfall_fee_cents_per_gallon=40,
    )
    unit = create_unit(
        outlet["id"], agreement["id"], serial_number="SN-CE-B-01",
        installed_at="2026-02-01T00:00:00Z",
    )
    activate_agreement(agreement["id"])
    task = create_task(unit["id"], "SANITATION", "2026-08-02T00:00:00Z")
    pin_clock("2026-08-10T00:00:00Z")
    evaluated = evaluate_task(task["id"], OFFICER)
    place_service_hold(unit["id"], TECH)
    return outlet, unit, task, evaluated


class TestServeBlockedByCalibration:
    def test_an_out_of_spec_machine_at_the_outlet_refuses_the_delivery(self, api):
        """PRD §3.7: "If any dispenser unit at that outlet carries
        `calibration_status` `OUT_OF_SPEC`, service is refused with
        `ERR_CALIBRATION_OUT_OF_SPEC` — the network will not top up a machine that
        is pouring off-ratio product."

        Design: Difficulty/cross_entity_state_dependency/stop_serve_blocked_by_out_of_spec_calibration_dimension
        """
        scenario = _arrived_stop_behind_an_out_of_spec_machine()
        assert scenario["forecast"]["requested_units"] == 34
        assert scenario["allocation"]["total_allocated_units"] == 32
        assert scenario["graded"]["calibration_outcome"] == "FAIL"
        machine = read_unit(scenario["unit"]["id"])
        assert machine["calibration_status"] == "OUT_OF_SPEC"
        assert machine["brix_ratio_last_measured"] == pytest.approx(5.40, abs=0.01)

        response = api.serve_stop(scenario["stop"]["id"], DRIVER)
        validate_error(response, ApiErrorId.ERR_CALIBRATION_OUT_OF_SPEC.value, 409)

        stop = read_stop(scenario["stop"]["id"])
        assert stop["status"] == "ARRIVED"
        assert stop["delivered_units"] == 0
        assert read_position(scenario["position"]["id"])["allocated_units"] == 32
        assert read_supply_item(scenario["item"]["id"])["reserved_pool_units"] == 32

    def test_bringing_the_machine_back_in_spec_lets_the_same_serve_through(self, api):
        """PRD §3.3: "A `PASS` sets the unit's `calibration_status` to `IN_SPEC` and
        a `FAIL` sets it to `OUT_OF_SPEC`; in both cases the measured value is
        written to the unit's `brix_ratio_last_measured` and the unit's `version`
        advances by one."

        Design: Difficulty/cross_entity_state_dependency/stop_serve_blocked_by_out_of_spec_calibration_dimension
        """
        scenario = _arrived_stop_behind_an_out_of_spec_machine()
        api.serve_stop(scenario["stop"]["id"], DRIVER)

        recalibrated = complete_task(
            scenario["passing_task"]["id"], TECH, measured_brix_ratio=5.10
        )
        assert recalibrated["calibration_outcome"] == "PASS"
        assert read_unit(scenario["unit"]["id"])["calibration_status"] == "IN_SPEC"

        served = serve_stop(scenario["stop"]["id"])
        assert served["status"] == "SERVED"
        assert served["delivered_units"] == 32

        position = read_position(scenario["position"]["id"])
        assert position["on_hand_units"] == 38
        assert position["allocated_units"] == 0
        assert position["planned_route_stop_id"] is None

        item = read_supply_item(scenario["item"]["id"])
        assert item["reserved_pool_units"] == 0
        assert item["national_allocation_units"] == 1000

        route = read_route(scenario["route"]["id"])
        assert route["committed_units"] == 32
        assert route["delivered_units"] == 0

        assert read_unit(scenario["unit"]["id"])["status"] == "IN_SERVICE"


class TestServiceHoldReleaseBlockedBySanitation:
    def test_an_overdue_sanitation_task_refuses_the_release(self, api):
        """PRD §3.3: "`RELEASE` moves it `SERVICE_HOLD → IN_SERVICE`, but is blocked
        while any maintenance task of that unit whose `task_type` is `SANITATION`
        sits in `OVERDUE`, in which case the release is refused with
        `ERR_SANITATION_OVERDUE`."

        Design: Difficulty/cross_entity_state_dependency/service_hold_release_blocked_by_overdue_sanitation_task
        """
        outlet, unit, _task, evaluated = _held_unit_with_an_overdue_sanitation_task()
        assert evaluated["status"] == "OVERDUE"
        assert evaluated["breach_kind"] == "DATE"
        before = read_outlet(outlet["id"])
        assert before["overdue_task_count"] == 1
        assert before["service_posture"] == "RESTRICTED"

        response = api.unit_service_hold(
            unit["id"], service_hold_payload("RELEASE"), TECH
        )
        validate_error(response, ApiErrorId.ERR_SANITATION_OVERDUE.value, 409)

        held = read_unit(unit["id"])
        assert held["status"] == "SERVICE_HOLD"
        assert held["version"] == 2

    def test_completing_the_sanitation_task_clears_both_the_gate_and_the_posture(
        self, api
    ):
        """PRD §3.5: "Completing a task that was in `OVERDUE` also lowers the
        outlet's `overdue_task_count` by one and recomputes `service_posture`, which
        is how an outlet works its way back from `FROZEN` to `RESTRICTED` and
        eventually to `OPEN`."

        Design: Difficulty/cross_entity_state_dependency/service_hold_release_blocked_by_overdue_sanitation_task
        """
        outlet, unit, task, _evaluated = _held_unit_with_an_overdue_sanitation_task()
        api.unit_service_hold(unit["id"], service_hold_payload("RELEASE"), TECH)

        completed = complete_task(task["id"], TECH)
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"].startswith("2026-08-10T00:00:00")
        assert completed["completed_by_user_id"] == TECH["X-User-ID"]

        cleared = read_outlet(outlet["id"])
        assert cleared["overdue_task_count"] == 0
        assert cleared["service_posture"] == "OPEN"

        released = validate_success(
            api.unit_service_hold(unit["id"], service_hold_payload("RELEASE"), TECH)
        )
        assert released["status"] == "IN_SERVICE"
        assert released["version"] == 3
        assert read_unit(unit["id"])["calibration_status"] == "UNVERIFIED"
