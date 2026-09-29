"""Multi-hop cascades that walk from one write to five consequences.

One telemetry reading trips a filter interval, freezes the outlet, skips its
pending stop and releases the allocation; one return confirmation terminates an
agreement, suspends the outlet and does the same to a different stop.
"""

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    api_client,
    activate_agreement,
    add_telemetry,
    allocate,
    add_stop,
    assess_shortfall_payload,
    create_agreement,
    create_outlet,
    create_position,
    create_route,
    create_supply_item,
    create_task,
    create_unit,
    evaluate_task,
    pin_clock,
    read_agreement,
    read_outlet,
    read_position,
    read_route,
    read_stop,
    read_supply_item,
    read_task,
    read_unit,
    recall_decision_payload,
    run_forecast,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ADMIN_ALT = TEST_USERS["admin_alt_headers"]
OFFICER = TEST_USERS["officer_headers"]
PLANNER = TEST_USERS["planner_headers"]


def _outlet_one_task_short_of_frozen():
    """Hard-water outlet: two overdue tasks, a filter task, and an allocated stop."""
    pin_clock("2026-08-01T00:00:00Z")
    outlet = create_outlet(
        name="Waterpark Snack Bar",
        account_code="ACCT-TC-A",
        region_code="R7",
        throughput_tier="MEDIUM",
        water_hardness_gpg=25,
    )
    agreement = create_agreement(
        outlet["id"],
        annual_commitment_gallons=6000,
        equipment_value_cents=480000,
        free_on_loan=True,
        shortfall_fee_cents_per_gallon=50,
    )
    unit = create_unit(
        outlet["id"],
        agreement["id"],
        serial_number="SN-TC-A-01",
        installed_at="2026-01-01T00:00:00Z",
    )
    activate_agreement(agreement["id"])
    item = create_supply_item(
        sku_code="COKE_CART_TC",
        brand_name="Coca-Cola",
        supply_form="CARTRIDGE",
        case_pack_units=4,
        ounces_per_unit=350,
        promotional=False,
        national_allocation_units=1000,
    )
    preventive = create_task(unit["id"], "PREVENTIVE", "2026-08-02T00:00:00Z")
    sanitation = create_task(unit["id"], "SANITATION", "2026-08-02T00:00:00Z")
    filter_task = create_task(
        unit["id"], "FILTER_CHANGE", "2027-06-01T00:00:00Z", gallon_interval=4000
    )
    pin_clock("2026-08-10T00:00:00Z")
    evaluate_task(preventive["id"])
    evaluate_task(sanitation["id"])
    add_telemetry(
        unit["id"], item["id"], 7000, "2026-08-09T00:00:00Z", window_days=7
    )
    position = create_position(outlet["id"], item["id"], 6)
    run_forecast(position["id"], "TRAILING_ACTUAL", 7)
    route = create_route(
        route_code="RT-TC-1",
        depot_region_code="R7",
        service_date="2026-08-11T00:00:00Z",
        van_code="V-31",
        capacity_units=500,
    )
    stop = add_stop(
        route["id"], outlet["id"], 1, "2026-08-11T08:00:00Z", "2026-08-11T10:00:00Z"
    )
    allocation = allocate(stop["id"], [position["id"]])
    return {
        "outlet": outlet,
        "unit": unit,
        "item": item,
        "filter_task": filter_task,
        "position": position,
        "route": route,
        "stop": stop,
        "allocation": allocation,
    }


def _recall_pending_outlet_with_a_pending_stop():
    """One-unit agreement in RECALL_PENDING whose outlet still holds a pending stop."""
    pin_clock("2026-10-01T00:00:00Z")
    outlet = create_outlet(
        name="Ferry Terminal Kiosk",
        account_code="ACCT-TC-B",
        region_code="R8",
        throughput_tier="MEDIUM",
        water_hardness_gpg=10,
    )
    agreement = create_agreement(
        outlet["id"],
        term_start_date="2026-01-01T00:00:00Z",
        term_end_date="2027-01-01T00:00:00Z",
        annual_commitment_gallons=8000,
        equipment_value_cents=600000,
        free_on_loan=True,
        shortfall_fee_cents_per_gallon=50,
    )
    unit = create_unit(
        outlet["id"],
        agreement["id"],
        serial_number="SN-TC-B-01",
        installed_at="2026-01-01T00:00:00Z",
    )
    activate_agreement(agreement["id"])
    item = create_supply_item(
        sku_code="COKE_CART_RC",
        brand_name="Coca-Cola",
        supply_form="CARTRIDGE",
        case_pack_units=4,
        ounces_per_unit=350,
        promotional=False,
        national_allocation_units=1000,
    )
    for ounces, reading_at in (
        (128126.72, "2026-02-15T00:00:00Z"),
        (192126.72, "2026-05-15T00:00:00Z"),
        (230526.72, "2026-08-15T00:00:00Z"),
    ):
        add_telemetry(unit["id"], item["id"], ounces, reading_at, window_days=30)
    add_telemetry(unit["id"], item["id"], 7000, "2026-09-28T00:00:00Z", window_days=7)
    position = create_position(outlet["id"], item["id"], 6)
    run_forecast(position["id"], "TRAILING_ACTUAL", 7)
    route = create_route(
        route_code="RT-RC-1",
        depot_region_code="R8",
        service_date="2026-10-02T00:00:00Z",
        van_code="V-41",
        capacity_units=500,
    )
    stop = add_stop(
        route["id"], outlet["id"], 1, "2026-10-02T08:00:00Z", "2026-10-02T10:00:00Z"
    )
    allocation = allocate(stop["id"], [position["id"]])
    assessed = validate_success(
        api_client.assess_shortfall(
            agreement["id"],
            assess_shortfall_payload("2026-01-01T00:00:00Z", "2026-10-01T00:00:00Z"),
            ADMIN_ALT,
        )
    )
    validate_success(
        api_client.recall_decision(
            agreement["id"], recall_decision_payload("RECALL"), OFFICER
        )
    )
    return {
        "outlet": outlet,
        "agreement": agreement,
        "unit": unit,
        "item": item,
        "position": position,
        "route": route,
        "stop": stop,
        "allocation": allocation,
        "assessed": assessed,
    }


class TestGallonBreachCascade:
    def test_one_reading_trips_the_filter_interval_and_freezes_the_outlet(self, api):
        """PRD §3.4: "A gallon breach drives such a task straight to `OVERDUE` with
        `breach_kind` `GALLON`, skipping the courtesy grace band entirely, which
        raises the outlet's `overdue_task_count` by one and forces a posture
        recomputation; and if that posture recomputation lands on `FROZEN`, the
        outlet's `PENDING` route stops are skipped with `skip_reason_code`
        `POSTURE_FROZEN` and their allocations are released back to the pool and
        the route."

        Design: Difficulty/transitive_cascade/telemetry_gallon_breach_cascades_to_frozen_posture_and_released_allocation
        """
        scenario = _outlet_one_task_short_of_frozen()
        assert read_task(scenario["filter_task"]["id"])[
            "effective_gallon_interval"
        ] == pytest.approx(2800.00, abs=0.01)
        assert scenario["allocation"]["total_allocated_units"] == 32

        add_telemetry(
            scenario["unit"]["id"], scenario["item"]["id"], 358400,
            "2026-08-09T12:00:00Z", window_days=7,
        )

        unit = read_unit(scenario["unit"]["id"])
        assert unit["lifetime_dispensed_gallons"] == pytest.approx(2854.69, abs=0.01)

        task = read_task(scenario["filter_task"]["id"])
        assert task["status"] == "OVERDUE"
        assert task["breach_kind"] == "GALLON"

        outlet = read_outlet(scenario["outlet"]["id"])
        assert outlet["overdue_task_count"] == 3
        assert outlet["service_posture"] == "FROZEN"

        stop = read_stop(scenario["stop"]["id"])
        assert stop["status"] == "SKIPPED"
        assert stop["skip_reason_code"] == "POSTURE_FROZEN"
        assert stop["delivered_units"] == 0

    def test_the_frozen_skip_releases_units_without_delivering_them(self, api):
        """PRD §2.10: "Releases are always the same four movements, applied to every
        outlet supply position whose `planned_route_stop_id` points at the stop
        being released: the position's `allocated_units` returns to 0, its
        `planned_route_stop_id` returns to null, the referenced supply item's
        `reserved_pool_units` is reduced by the released amount, and the owning
        route's `committed_units` is reduced by the released amount."

        Design: Difficulty/transitive_cascade/telemetry_gallon_breach_cascades_to_frozen_posture_and_released_allocation
        """
        scenario = _outlet_one_task_short_of_frozen()

        add_telemetry(
            scenario["unit"]["id"], scenario["item"]["id"], 358400,
            "2026-08-09T12:00:00Z", window_days=7,
        )

        position = read_position(scenario["position"]["id"])
        assert position["allocated_units"] == 0
        assert position["planned_route_stop_id"] is None
        assert position["on_hand_units"] == 6
        assert position["requested_units"] == 34

        item = read_supply_item(scenario["item"]["id"])
        assert item["reserved_pool_units"] == 0
        assert item["national_allocation_units"] == 1000

        route = read_route(scenario["route"]["id"])
        assert route["committed_units"] == 0
        assert route["status"] == "PLANNED"


class TestConfirmReturnCascade:
    def test_last_return_terminates_the_agreement_and_suspends_the_outlet(self, api):
        """PRD §2.10: "when the last dispenser of an agreement is confirmed
        returned, the agreement terminates, and if that leaves the outlet with no
        agreement in `DRAFT`, `ACTIVE`, `SHORTFALL_REVIEW` or `RECALL_PENDING`, the
        outlet itself is suspended, which again skips its pending stops and
        releases their allocations — four hops from one confirmation."

        Design: Difficulty/transitive_cascade/confirm_return_cascades_to_terminated_agreement_suspended_outlet_and_skipped_stop
        """
        scenario = _recall_pending_outlet_with_a_pending_stop()
        assert scenario["assessed"]["assessed_fee_cents"] == 82118
        assert scenario["assessed"]["recall_exposure_cents"] == 546000
        assert read_agreement(scenario["agreement"]["id"])["status"] == "RECALL_PENDING"
        assert read_unit(scenario["unit"]["id"])["status"] == "RECALL_STAGED"

        returned = validate_success(api.confirm_return(scenario["unit"]["id"], ADMIN))
        assert returned["status"] == "RETURNED"

        agreement = read_agreement(scenario["agreement"]["id"])
        assert agreement["status"] == "TERMINATED"
        assert agreement["assessed_fee_cents"] == 82118
        assert agreement["recall_exposure_cents"] == 546000

        outlet = read_outlet(scenario["outlet"]["id"])
        assert outlet["status"] == "SUSPENDED"
        assert outlet["service_posture"] == "OPEN"

    def test_the_suspension_skip_is_stamped_outlet_closed_and_returns_the_pool(self, api):
        """PRD §3.7: "The server also skips `PENDING` stops on its own initiative,
        and the reason it stamps identifies the cause: `POSTURE_FROZEN` when the
        outlet's posture became `FROZEN`, `OUTLET_CLOSED` when the outlet was
        suspended, and `ACCESS_DENIED` when the route was cancelled."

        Design: Difficulty/transitive_cascade/confirm_return_cascades_to_terminated_agreement_suspended_outlet_and_skipped_stop
        """
        scenario = _recall_pending_outlet_with_a_pending_stop()
        assert scenario["allocation"]["total_allocated_units"] == 32

        validate_success(api.confirm_return(scenario["unit"]["id"], ADMIN))

        stop = read_stop(scenario["stop"]["id"])
        assert stop["status"] == "SKIPPED"
        assert stop["skip_reason_code"] == "OUTLET_CLOSED"
        assert stop["delivered_units"] == 0

        position = read_position(scenario["position"]["id"])
        assert position["allocated_units"] == 0
        assert position["planned_route_stop_id"] is None
        assert position["on_hand_units"] == 6

        item = read_supply_item(scenario["item"]["id"])
        assert item["reserved_pool_units"] == 0
        assert item["national_allocation_units"] == 1000

        route = read_route(scenario["route"]["id"])
        assert route["committed_units"] == 0
        assert route["status"] == "PLANNED"
