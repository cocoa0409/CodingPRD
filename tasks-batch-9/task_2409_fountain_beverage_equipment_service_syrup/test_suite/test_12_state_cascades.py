"""Declared hops that move rows other than the one being acted on.

The calibration cycle, the two-dimension independence, draft supersession, the two
different stop-skip cascades, the delivery and release ledgers, the overdue-task
reconciliation, the confirm-return sweep and the two parts-compensating hops.
"""

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    activate_agreement,
    add_stop,
    add_telemetry,
    allocate,
    api_client,
    arrive_call,
    arrive_stop,
    assess_shortfall_payload,
    change_outlet_status,
    complete_task,
    create_agreement,
    create_agreement_payload,
    create_call,
    create_outlet,
    create_position,
    create_route,
    create_supply_item,
    create_task,
    create_unit,
    create_van_stock,
    dispatch_call,
    dispatch_route,
    escalate_call,
    evaluate_task,
    outlet_version,
    pin_clock,
    place_compliance_hold,
    place_service_hold,
    read_agreement,
    read_call,
    read_outlet,
    read_position,
    read_route,
    read_stop,
    read_supply_item,
    read_task,
    read_unit,
    read_van_stock,
    recall_decision_payload,
    run_forecast,
    serve_stop,
    skip_stop,
    waive_task,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
PLANNER = TEST_USERS["planner_headers"]
DRIVER = TEST_USERS["driver_headers"]
TECH = TEST_USERS["technician_headers"]
OFFICER = TEST_USERS["officer_headers"]
OFFICER_ALT = TEST_USERS["officer_alt_headers"]

CLOCK = "2026-08-01T00:00:00Z"


def _outlet():
    pin_clock(CLOCK)
    return create_outlet(
        name="Riverside Diner", account_code="OUT-1001", region_code="R-WEST"
    )


def _outlet_agreement_and_unit(activate=False, **agreement_overrides):
    """An outlet, its agreement and one machine placed under that agreement."""
    outlet = _outlet()
    agreement = create_agreement(
        outlet["id"],
        annual_commitment_gallons=8000,
        equipment_value_cents=480000,
        **agreement_overrides,
    )
    unit = create_unit(
        outlet["id"], agreement["id"],
        serial_number="SN-9001", installed_at="2025-11-01T00:00:00Z",
    )
    if activate:
        activate_agreement(agreement["id"])
    return outlet, agreement, unit


def _route_with_two_stops_dispatched_and_first_arrived():
    """Two stops at one outlet on a DISPATCHED route; the first has been arrived at."""
    outlet = _outlet()
    route = create_route(
        route_code="RT-01", depot_region_code="R-WEST",
        service_date="2026-08-03T00:00:00Z", van_code="VAN-7", capacity_units=60,
    )
    first = add_stop(
        route["id"], outlet["id"], 1, "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z"
    )
    second = add_stop(
        route["id"], outlet["id"], 2, "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z"
    )
    dispatch_route(route["id"])
    arrive_stop(first["id"])
    return outlet, route, first, second


def _stop_holding_a_twelve_unit_grant(second_stop=False):
    """A 12-unit grant on a capacity-60 route drawn from a 100-unit national pool."""
    outlet, agreement, unit = _outlet_agreement_and_unit(activate=True)
    item = create_supply_item(
        sku_code="SKU-COLA",
        brand_name="Cola Classic",
        supply_form="CARTRIDGE",
        case_pack_units=4,
        ounces_per_unit=1000,
        promotional=False,
        national_allocation_units=100,
    )
    add_telemetry(unit["id"], item["id"], 7000, "2026-07-28T00:00:00Z", window_days=7)
    position = create_position(outlet["id"], item["id"], 2)
    forecast = run_forecast(position["id"], "TRAILING_ACTUAL", 7)
    route = create_route(
        route_code="RT-01", depot_region_code="R-WEST",
        service_date="2026-08-03T00:00:00Z", van_code="VAN-7", capacity_units=60,
    )
    stop = add_stop(
        route["id"], outlet["id"], 1, "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z"
    )
    other = (
        add_stop(
            route["id"], outlet["id"], 2, "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z"
        )
        if second_stop
        else None
    )
    allocation = allocate(stop["id"], [position["id"]])
    return {
        "outlet": outlet,
        "item": item,
        "position": position,
        "forecast": forecast,
        "route": route,
        "stop": stop,
        "other_stop": other,
        "allocation": allocation,
    }


def _overdue_preventive_task():
    """A PREVENTIVE task due 2026-07-01 that has already been evaluated OVERDUE."""
    outlet, _agreement, unit = _outlet_agreement_and_unit()
    task = create_task(unit["id"], "PREVENTIVE", "2026-07-01T00:00:00Z")
    evaluated = evaluate_task(task["id"], OFFICER)
    return outlet, task, evaluated


class TestCalibrationDimension:
    def test_a_machine_may_travel_the_calibration_cycle_any_number_of_times(self, api):
        """PRD §3.3: "The declared movements on this dimension are therefore
        `UNVERIFIED → IN_SPEC` and `UNVERIFIED → OUT_OF_SPEC` on a machine that has
        never been verified, `IN_SPEC → OUT_OF_SPEC` when a previously good machine
        drifts out, and `OUT_OF_SPEC → IN_SPEC` when a re-calibration brings it back —
        the last two forming a cycle that a machine may travel any number of times."

        Design: Corner/state_machines/calibration_dimension_cycles_in_spec_out_of_spec_in_spec
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit()
        first = create_task(unit["id"], "BRIX_CALIBRATION", "2026-08-10T00:00:00Z")
        second = create_task(unit["id"], "BRIX_CALIBRATION", "2026-08-11T00:00:00Z")
        third = create_task(unit["id"], "BRIX_CALIBRATION", "2026-08-12T00:00:00Z")

        assert complete_task(first["id"], TECH, measured_brix_ratio=5.10)[
            "calibration_outcome"
        ] == "PASS"
        assert read_unit(unit["id"])["calibration_status"] == "IN_SPEC"

        assert complete_task(second["id"], TECH, measured_brix_ratio=5.40)[
            "calibration_outcome"
        ] == "FAIL"
        assert read_unit(unit["id"])["calibration_status"] == "OUT_OF_SPEC"

        assert complete_task(third["id"], TECH, measured_brix_ratio=5.00)[
            "calibration_outcome"
        ] == "PASS"
        recovered = read_unit(unit["id"])
        assert recovered["calibration_status"] == "IN_SPEC"
        assert recovered["brix_ratio_last_measured"] == pytest.approx(5.00, abs=0.01)
        assert recovered["status"] == "IN_SERVICE"

    def test_a_held_machine_still_accepts_a_calibration(self, api):
        """PRD §3.3: "The two never constrain each other: a machine may perfectly
        legitimately be in `SERVICE_HOLD` and `IN_SPEC` at the same instant, and each
        dimension advances only through its own triggers."

        Design: Corner/state_machines/unit_service_and_calibration_dimensions_move_independently
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit()
        task = create_task(unit["id"], "BRIX_CALIBRATION", "2026-08-10T00:00:00Z")
        place_service_hold(unit["id"], TECH)

        graded = complete_task(task["id"], TECH, measured_brix_ratio=5.15)
        assert graded["calibration_outcome"] == "PASS"

        after = read_unit(unit["id"])
        assert after["calibration_status"] == "IN_SPEC"
        assert after["status"] == "SERVICE_HOLD"
        assert after["brix_ratio_last_measured"] == pytest.approx(5.15, abs=0.01)


class TestAgreementSupersession:
    def test_a_second_draft_expires_the_first_one(self, api):
        """PRD §3.2: "Drafting has one further consequence that is easy to miss and is
        the entire reason the write is version-guarded: any **other** agreement of the
        same outlet that is still in `DRAFT` is superseded by the new one and moves
        `DRAFT → EXPIRED`, with its own `version` advancing by one."

        Design: Corner/state_machines/new_agreement_supersedes_prior_draft_agreement_to_expired
        """
        outlet = _outlet()
        first = create_agreement(
            outlet["id"], annual_commitment_gallons=8000, equipment_value_cents=480000
        )
        refreshed_version = outlet_version(outlet["id"])

        second = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    outlet["id"], refreshed_version,
                    term_start_date="2026-08-01T00:00:00Z",
                    term_end_date="2027-08-01T00:00:00Z",
                    annual_commitment_gallons=9000,
                    equipment_value_cents=500000,
                ),
                ADMIN,
            ),
            201,
        )

        superseded = read_agreement(first["id"])
        assert superseded["status"] == "EXPIRED"
        assert superseded["version"] == 2
        assert second["status"] == "DRAFT"
        assert second["version"] == 1
        assert outlet_version(outlet["id"]) == refreshed_version + 1


class TestOutletCascadesOntoStops:
    def test_suspension_skips_the_arrived_stop_as_well_as_the_pending_one(self, api):
        """PRD §3.1: "Whenever an outlet moves `ACTIVE → SUSPENDED`, every route stop
        of that outlet still sitting in `PENDING` **or** `ARRIVED` is driven to
        `SKIPPED` and stamped with `skip_reason_code` `OUTLET_CLOSED`, and every one of
        those skipped stops releases the consumable it was holding exactly as
        described in §2.10."

        Design: Corner/state_machines/suspend_outlet_skips_both_pending_and_arrived_stops_as_outlet_closed
        """
        outlet, route, first, second = _route_with_two_stops_dispatched_and_first_arrived()
        assert read_stop(first["id"])["status"] == "ARRIVED"
        assert read_stop(second["id"])["status"] == "PENDING"

        change_outlet_status(outlet["id"], "SUSPEND")

        assert read_outlet(outlet["id"])["status"] == "SUSPENDED"
        for stop_id in (first["id"], second["id"]):
            skipped = read_stop(stop_id)
            assert skipped["status"] == "SKIPPED"
            assert skipped["skip_reason_code"] == "OUTLET_CLOSED"
        assert read_route(route["id"])["status"] == "DISPATCHED"

    def test_a_compliance_hold_spares_the_stop_the_driver_has_reached(self, api):
        """PRD §3.1: "Placing sets `open_compliance_hold_count` to 1, records the
        acting `X-User-ID` in `last_hold_placed_by_user_id`, recomputes
        `service_posture`, which necessarily lands on `FROZEN`, drives the outlet's
        `PENDING` stops to `SKIPPED` with `skip_reason_code` `POSTURE_FROZEN`, releases
        each of those stops' allocations back to the pool and the route, and increments
        the outlet's `version` by one."

        Design: Corner/state_machines/compliance_hold_skips_only_pending_stops_and_spares_arrived_stop
        """
        outlet, _route, first, second = _route_with_two_stops_dispatched_and_first_arrived()

        place_compliance_hold(outlet["id"], OFFICER)

        held = read_outlet(outlet["id"])
        assert held["status"] == "ACTIVE"
        assert held["open_compliance_hold_count"] == 1
        assert held["service_posture"] == "FROZEN"

        spared = read_stop(first["id"])
        assert spared["status"] == "ARRIVED"
        assert spared["skip_reason_code"] is None

        skipped = read_stop(second["id"])
        assert skipped["status"] == "SKIPPED"
        assert skipped["skip_reason_code"] == "POSTURE_FROZEN"

    def test_reinstatement_leaves_the_skipped_stop_where_it_fell(self, api):
        """PRD §3.1: "Reinstatement is deliberately asymmetric: moving
        `SUSPENDED → ACTIVE` recomputes the posture and bumps the version, but it does
        **not** resurrect the stops that were skipped, and it does not re-reserve the
        units that were released."

        Design: Corner/state_machines/reinstate_does_not_resurrect_stops_skipped_by_the_suspension
        """
        outlet = _outlet()
        route = create_route(
            route_code="RT-01", depot_region_code="R-WEST",
            service_date="2026-08-03T00:00:00Z", van_code="VAN-7", capacity_units=60,
        )
        stop = add_stop(
            route["id"], outlet["id"], 1, "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z"
        )
        change_outlet_status(outlet["id"], "SUSPEND")

        reinstated = change_outlet_status(outlet["id"], "REINSTATE")
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["service_posture"] == "OPEN"

        after = read_stop(stop["id"])
        assert after["status"] == "SKIPPED"
        assert after["skip_reason_code"] == "OUTLET_CLOSED"


class TestStopExecutionLedgers:
    def test_serving_hands_the_units_over_and_consumes_the_pool_commitment(self, api):
        """PRD §3.7: "Serving a stop moves it `ARRIVED → SERVED` and is the moment
        stock actually changes hands: for every position pointing at this stop, the
        position's `allocated_units` are added to its `on_hand_units`, then
        `allocated_units` returns to 0 and `planned_route_stop_id` to null; the stop's
        `delivered_units` is written as the total units handed over; the SKU's
        `reserved_pool_units` is reduced per SKU by what was delivered, because that
        pool commitment has now been consumed rather than returned; and the route's
        `committed_units` is deliberately **not** reduced."

        Design: Corner/state_machines/serve_stop_moves_allocated_units_into_on_hand_and_consumes_the_pool
        """
        scenario = _stop_holding_a_twelve_unit_grant()
        assert scenario["allocation"]["total_allocated_units"] == 12
        dispatch_route(scenario["route"]["id"])
        arrive_stop(scenario["stop"]["id"])

        served = serve_stop(scenario["stop"]["id"])
        assert served["status"] == "SERVED"
        assert served["delivered_units"] == 12

        position = read_position(scenario["position"]["id"])
        assert position["on_hand_units"] == 14
        assert position["allocated_units"] == 0
        assert position["planned_route_stop_id"] is None
        assert position["alert_level"] == "NONE"

        item = read_supply_item(scenario["item"]["id"])
        assert item["reserved_pool_units"] == 0
        assert item["national_allocation_units"] == 100

        assert read_route(scenario["route"]["id"])["committed_units"] == 12

    def test_skipping_the_arrived_stop_gives_everything_back(self, api):
        """PRD §3.7: "Either skip writes that reason, releases every position pointing
        at the stop through the four release movements of §2.10 — allocated units to 0,
        stop link to null, the SKU's `reserved_pool_units` down, the route's
        `committed_units` down — and advances the `version` of every mutated row by
        one."

        Design: Corner/state_machines/skip_arrived_stop_releases_allocation_and_restores_route_capacity
        """
        scenario = _stop_holding_a_twelve_unit_grant()
        dispatch_route(scenario["route"]["id"])
        arrive_stop(scenario["stop"]["id"])

        skipped = skip_stop(scenario["stop"]["id"], "ACCESS_DENIED")
        assert skipped["status"] == "SKIPPED"
        assert skipped["skip_reason_code"] == "ACCESS_DENIED"
        assert skipped["delivered_units"] == 0

        position = read_position(scenario["position"]["id"])
        assert position["on_hand_units"] == 2
        assert position["allocated_units"] == 0
        assert position["planned_route_stop_id"] is None

        assert read_supply_item(scenario["item"]["id"])["reserved_pool_units"] == 0
        assert read_route(scenario["route"]["id"])["committed_units"] == 0

    def test_completion_counts_only_what_was_actually_served(self, api):
        """PRD §3.7: "Completion moves it `DISPATCHED → COMPLETED`, takes no request
        body and no expected-version field, and is permitted only once every stop of
        the route has reached `SERVED` or `SKIPPED`; it recomputes the route's
        `delivered_units` as the sum of `delivered_units` over its `SERVED` stops and
        advances the route's `version` by one."

        Design: Corner/state_machines/route_complete_recomputes_delivered_units_over_served_stops_only
        """
        scenario = _stop_holding_a_twelve_unit_grant(second_stop=True)
        dispatch_route(scenario["route"]["id"])
        arrive_stop(scenario["stop"]["id"])
        serve_stop(scenario["stop"]["id"])
        skip_stop(scenario["other_stop"]["id"], "ACCESS_DENIED")

        completed = validate_success(
            api.complete_route(scenario["route"]["id"], PLANNER)
        )
        assert completed["status"] == "COMPLETED"
        assert completed["delivered_units"] == 12

        served = read_stop(scenario["stop"]["id"])
        assert served["status"] == "SERVED"
        assert served["delivered_units"] == 12

        skipped = read_stop(scenario["other_stop"]["id"])
        assert skipped["status"] == "SKIPPED"
        assert skipped["delivered_units"] == 0


class TestOverdueTaskReconciliation:
    def test_completing_the_overdue_task_walks_the_posture_back_to_open(self, api):
        """PRD §3.5: "Completing a task that was in `OVERDUE` also lowers the outlet's
        `overdue_task_count` by one and recomputes `service_posture`, which is how an
        outlet works its way back from `FROZEN` to `RESTRICTED` and eventually to
        `OPEN`."

        Design: Corner/state_machines/completing_an_overdue_task_decrements_counter_and_restores_posture
        """
        outlet, task, evaluated = _overdue_preventive_task()
        assert evaluated["status"] == "OVERDUE"
        before = read_outlet(outlet["id"])
        assert before["overdue_task_count"] == 1
        assert before["service_posture"] == "RESTRICTED"

        completed = complete_task(task["id"], TECH)
        assert completed["status"] == "COMPLETED"
        assert completed["breach_kind"] == "DATE"
        assert completed["completed_by_user_id"] == TECH["X-User-ID"]

        after = read_outlet(outlet["id"])
        assert after["overdue_task_count"] == 0
        assert after["service_posture"] == "OPEN"

    def test_waiving_the_overdue_task_reconciles_the_same_two_figures(self, api):
        """PRD §3.5: "The waiver records that reason and the acting `X-User-ID` in
        `waived_by_user_id`, moves the task to the terminal `WAIVED` state and
        increments its `version` by one; waiving a task that was `OVERDUE` also
        decrements the outlet's `overdue_task_count` and recomputes `service_posture`."

        Design: Corner/state_machines/waiving_an_overdue_task_decrements_counter_and_restores_posture
        """
        outlet, task, _evaluated = _overdue_preventive_task()

        waived = waive_task(
            task["id"], "Unit scheduled for replacement", OFFICER_ALT
        )
        assert waived["status"] == "WAIVED"
        assert waived["waiver_reason"] == "Unit scheduled for replacement"
        assert waived["waived_by_user_id"] == OFFICER_ALT["X-User-ID"]
        assert waived["completed_at"] is None

        after = read_outlet(outlet["id"])
        assert after["overdue_task_count"] == 0
        assert after["service_posture"] == "OPEN"


class TestConfirmReturnSweep:
    def test_confirming_the_return_waives_the_task_and_cancels_the_call(self, api):
        """PRD §3.3: "Confirming a return does all of the following in one request:
        every maintenance task of that unit currently in `SCHEDULED`, `DUE` or
        `OVERDUE` is driven to `WAIVED` with its `waiver_reason` set to the literal
        string `EQUIPMENT_RETURNED`, and each such task that was leaving `OVERDUE`
        lowers the outlet's `overdue_task_count` by one and triggers a posture
        recomputation; every service call of that unit currently in `OPEN`,
        `DISPATCHED`, `ON_SITE` or `ESCALATED` is driven to `CANCELLED`, returning any
        van parts it was holding to the van; and if that confirmation leaves every unit
        of the agreement `RETURNED`, the agreement moves `RECALL_PENDING →
        TERMINATED`, which may in turn suspend the outlet and skip its pending stops as
        described in §2.10 and §3.1."

        Design: Corner/state_machines/confirm_return_waives_open_tasks_and_cancels_open_service_calls
        """
        pin_clock(CLOCK)
        outlet = create_outlet(
            name="Riverside Diner", account_code="OUT-1001", region_code="R-WEST"
        )
        agreement = create_agreement(
            outlet["id"],
            annual_commitment_gallons=8000,
            equipment_value_cents=450000,
        )
        unit = create_unit(
            outlet["id"], agreement["id"],
            serial_number="SN-9001", installed_at="2026-07-20T00:00:00Z",
        )
        activate_agreement(agreement["id"])
        task = create_task(unit["id"], "SANITATION", "2026-09-01T00:00:00Z")
        call = create_call(unit["id"], "CO2_LOW", CLOCK)

        assessed = validate_success(
            api.assess_shortfall(
                agreement["id"],
                assess_shortfall_payload(
                    "2026-07-01T00:00:00Z", "2026-10-01T00:00:00Z",
                    exposure_variant="BOOK_VALUE",
                ),
                ADMIN,
            )
        )
        assert assessed["status"] == "SHORTFALL_REVIEW"
        recalled = validate_success(
            api.recall_decision(
                agreement["id"], recall_decision_payload("RECALL"), OFFICER
            )
        )
        assert recalled["status"] == "RECALL_PENDING"
        assert read_unit(unit["id"])["status"] == "RECALL_STAGED"

        returned = validate_success(api.confirm_return(unit["id"], ADMIN))
        assert returned["status"] == "RETURNED"

        swept_task = read_task(task["id"])
        assert swept_task["status"] == "WAIVED"
        assert swept_task["waiver_reason"] == "EQUIPMENT_RETURNED"
        assert read_call(call["id"])["status"] == "CANCELLED"


class TestServiceCallParts:
    def test_escalation_undoes_the_dispatch_field_by_field(self, api):
        """PRD §3.8: "Escalation fully reverses the parts reservation as a compensating
        movement — every unit held in `reserved_units` for this call returns to
        `on_van_units`, and the call's `reserved_part_units` returns to 0 with
        `reserved_part_stock_id` set to null — raises `escalation_count` by one, clears
        `van_code`, `scheduled_window_start`, `scheduled_window_end` and
        `assigned_tech_user_id` so the call is free for re-dispatch, and advances both
        the call's and the van row's `version` by one."

        Design: Corner/state_machines/escalate_clears_dispatch_assignment_fields_and_counts_the_loop
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit(activate=True)
        create_van_stock("VAN-7", "PUMP_ASSY_12", 5)
        call = create_call(unit["id"], "LEAK", CLOCK)
        dispatch_call(
            call["id"], "VAN-7", "2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z", TECH,
            part_sku="PUMP_ASSY_12", part_units=2,
        )
        arrive_call(call["id"], TECH)

        escalated = escalate_call(call["id"], "PARTS_INSUFFICIENT", TECH)
        assert escalated["status"] == "ESCALATED"
        assert escalated["escalation_count"] == 1
        assert escalated["van_code"] is None
        assert escalated["scheduled_window_start"] is None
        assert escalated["scheduled_window_end"] is None
        assert escalated["assigned_tech_user_id"] is None
        assert escalated["reserved_part_stock_id"] is None
        assert escalated["reserved_part_units"] == 0
        assert escalated["severity_score"] == 55
        assert escalated["severity"] == "ROUTINE"

    def test_cancelling_before_the_visit_puts_the_parts_back_on_the_van(self, api):
        """PRD §3.8: "Where a reservation is being held — which can only be the case
        from `DISPATCHED` — cancellation applies exactly the same compensating release
        as escalation, returning every reserved unit to `on_van_units`."

        Design: Corner/state_machines/cancel_dispatched_service_call_returns_reserved_parts_to_the_van
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit(activate=True)
        stock = create_van_stock("VAN-7", "PUMP_ASSY_12", 5)
        call = create_call(unit["id"], "NO_POUR", CLOCK)
        dispatch_call(
            call["id"], "VAN-7", "2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z", TECH,
            part_sku="PUMP_ASSY_12", part_units=2,
        )
        reserved = read_van_stock(stock["id"])
        assert reserved["on_van_units"] == 3
        assert reserved["reserved_units"] == 2

        cancelled = validate_success(api.cancel_service_call(call["id"], ADMIN))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["reserved_part_units"] == 0
        assert cancelled["reserved_part_stock_id"] is None

        van = read_van_stock(stock["id"])
        assert van["on_van_units"] == 5
        assert van["reserved_units"] == 0
        assert van["consumed_units"] == 0
        assert van["initial_units"] == 5
        assert van["restocked_units"] == 0
