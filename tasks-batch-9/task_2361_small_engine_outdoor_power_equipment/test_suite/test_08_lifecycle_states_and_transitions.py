"""Lifecycle states, declared transitions and the refusals that guard them.

Every test starts from an empty database with the logical plant clock positioned at
the reference instant, and builds the states it needs through the documented
endpoints only.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    build_and_release_unit,
    build_certification_family,
    build_engine_platform,
    build_order_version,
    build_product_model,
    build_service_part,
    build_supplier,
    cancel_engine_unit,
    close_machining_run_payload,
    complete_durability_test_payload,
    create_engine_unit_payload,
    hot_test_payload,
    hot_test_unit,
    inspect_component_lot,
    inspect_component_lot_payload,
    is_iso8601_timestamp,
    open_machining_run,
    plan_build_order,
    raise_parts_request,
    read_build_order,
    read_durability_run,
    read_engine_unit,
    read_family,
    read_lot,
    read_machining_run,
    read_service_part,
    read_supplier_scorecard,
    receive_component_lot,
    record_line_audit,
    record_line_audit_payload,
    record_torque,
    release_engine_unit,
    rework_engine_unit,
    run_allocations,
    schedule_durability_run,
    schedule_line_audit,
    stage_engine_unit,
    torque_readings_at,
    torque_record_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANT_ADMIN = TEST_USERS["plant_admin_headers"]
CERTIFICATION_ENGINEER = TEST_USERS["certification_engineer_headers"]
COMPLIANCE_OFFICER = TEST_USERS["compliance_officer_headers"]
QUALITY_ENGINEER = TEST_USERS["quality_engineer_headers"]
PRODUCTION_PLANNER = TEST_USERS["production_planner_headers"]
CHANNEL_PARTNER = TEST_USERS["channel_partner_headers"]

OUT_OF_BAND_TORQUE_READINGS = torque_readings_at(22.0, 22.1, 21.9, 23.20)


def _stage_second_unit(scenario, serial_number="SN-0002"):
    """A sibling unit on the same order, staged from the same upstream records."""
    return stage_engine_unit(scenario, serial_number)


class TestDeclaredInitialStates:
    """Each lifecycle opens in the state its own rules declare."""

    def test_certification_chain_entities_open_in_their_declared_initial_states(
        self, canonical_clock
    ):
        """PRD §3.1: "A newly declared family opens in `status` `DRAFT` with `cumulative_audit_failures` at 0, and with `deterioration_factor`, `certified_emission_g_per_kwh`, `compliance_margin_pct`, `submitted_by_user_id`, `certified_by_user_id`, `certified_at` and `audit_hold_at` all empty."

        PRD §2.5: "`version` is an integer that starts at 1 when the row is created and increments by 1 on every mutation of that row — including mutations the server performs on its own initiative, such as a derived counter being recomputed or a cascade imposing a hold."
        PRD §3.1: "The new platform's `certification_posture` is initialised immediately by the projection in §2.7 from the owning family's current status — so a platform created under a `DRAFT` family opens at `PENDING`, and one created under a family already in `DURABILITY_TESTING` opens at `RESTRICTED`."
        PRD §3.2: "A successful schedule creates the run in `status` `SCHEDULED` with its `df_method` projected from the family's `emission_standard` — `MULTIPLICATIVE` for `EPA_PHASE3` and `ADDITIVE` for `CARB_2024` — leaving `accumulated_hours`, `final_emission_g_per_kwh`, `computed_deterioration_factor` and `completed_at` empty and `extrapolated` false."
        PRD §3.3: "A new model opens in `status` `DRAFT` with `released_at` empty; the lifecycle runs `DRAFT`, `RELEASED` and `SUSPENDED`, with no terminal state — a suspended model can come back."

        Design: Corner/state_machines/initial_state_of_all_twelve_state_machines_on_creation
        """
        family = build_certification_family(family_code="2027-EPA-INIT")
        assert family["status"] == "DRAFT"
        assert family["version"] == 1
        assert family["cumulative_audit_failures"] == 0
        assert family["deterioration_factor"] is None
        assert family["certified_at"] is None

        platform = build_engine_platform(
            family["id"],
            platform_code="200INIT",
            displacement_cc=200,
            torque_spec_nm=21.0,
        )
        assert platform["certification_posture"] == "PENDING"

        run = schedule_durability_run(family["id"], platform["id"])
        assert run["status"] == "SCHEDULED"
        assert run["computed_deterioration_factor"] is None
        assert run["completed_at"] is None
        assert run["extrapolated"] is False
        assert run["df_method"] == "MULTIPLICATIVE"

        model = build_product_model(
            platform["id"],
            model_code="WM-21-INIT",
            channel="DEALER",
            dealer_share_pct=1.00,
            mass_retail_cap_units=0,
        )
        assert model["status"] == "DRAFT"
        assert model["released_at"] is None

    def test_supply_and_production_entities_open_in_their_declared_initial_states(
        self, released_order_plant
    ):
        """PRD §3.4: "A new supplier opens with `approval_status` `APPROVED`, `incoming_inspection_level` `NORMAL`, `rolling_defect_ppm` 0, `inspected_lot_count` 0 and `consecutive_accepted_lots` 0."

        PRD §3.4: "On receipt the lot opens in `status` `RECEIVED` with `component_category` copied from the supplier, `accepted_qty`, `consumed_qty` and `remaining_qty` at 0, `defects_found` and `defect_ppm` empty and `deviation_flag` false."
        PRD §3.5: "A new run opens in `status` `OPEN` with `measurements` empty, `sample_count` 0, and `mean_mm`, `sigma_mm`, `cpk` and `closed_at` all empty."
        PRD §3.6: "A successful plan opens the order in `status` `PLANNED` with `allocation_status` `UNALLOCATED`, all of `staged_quantity`, `built_quantity`, `allocated_dealer_units`, `allocated_mass_retail_units` and `unallocated_units` at 0, and `allocation_run_at`, `held_reason`, `status_before_hold` and `released_at` empty."
        PRD §3.7: "A successful staging creates the unit with `build_state` `STAGED` and `conformance_state` `PENDING`, `rework_count` at 0, and `torque_readings`, `out_of_spec_fastener_count`, `measured_rpm`, `measured_emission_g_per_kwh`, `hot_test_emission_threshold` and `released_at` all empty."
        PRD §3.8: "The audit opens in `status` `SCHEDULED` with `units_tested`, `units_failed`, `max_measured_emission_g_per_kwh`, `failure_rate`, `failure_reason` and `recorded_by_user_id` all empty; the lifecycle runs `SCHEDULED`, `PASSED` and `FAILED`, and both outcomes are terminal."

        Design: Corner/state_machines/initial_state_of_all_twelve_state_machines_on_creation
        """
        scenario = released_order_plant

        supplier = build_supplier(
            supplier_code="SUP-INIT",
            name="Init Components",
            component_category="CARBURETOR",
        )
        assert supplier["approval_status"] == "APPROVED"
        assert supplier["incoming_inspection_level"] == "NORMAL"
        assert supplier["rolling_defect_ppm"] == 0
        assert supplier["inspected_lot_count"] == 0
        assert supplier["consecutive_accepted_lots"] == 0

        lot = receive_component_lot(supplier["id"], lot_code="CB-INIT", lot_quantity=800)
        assert lot["status"] == "RECEIVED"
        assert lot["component_category"] == "CARBURETOR"
        assert lot["accepted_qty"] == 0
        assert lot["consumed_qty"] == 0
        assert lot["remaining_qty"] == 0
        assert lot["defects_found"] is None
        assert lot["defect_ppm"] is None
        assert lot["deviation_flag"] is False

        machining_run = open_machining_run(
            scenario.platform_id,
            scenario.casting_lot_id,
            component_type="CRANKSHAFT",
            lsl_mm=34.98000,
            usl_mm=35.02000,
        )
        assert machining_run["status"] == "OPEN"
        assert machining_run["sample_count"] == 0
        assert machining_run["cpk"] is None
        assert machining_run["closed_at"] is None

        planned_order = plan_build_order(
            scenario.model_id, scenario.line_id, week_span=1, planned_quantity=4
        )
        assert planned_order["status"] == "PLANNED"
        assert planned_order["allocation_status"] == "UNALLOCATED"
        assert planned_order["staged_quantity"] == 0
        assert planned_order["built_quantity"] == 0
        assert planned_order["released_at"] is None

        unit = stage_engine_unit(scenario, "SN-0001")
        assert unit["build_state"] == "STAGED"
        assert unit["conformance_state"] == "PENDING"
        assert unit["rework_count"] == 0
        assert unit["torque_readings"] is None
        assert unit["measured_rpm"] is None
        assert unit["hot_test_emission_threshold"] is None
        assert unit["released_at"] is None

        audit = schedule_line_audit(scenario.build_order_id, audit_week="2026-09-14")
        assert audit["status"] == "SCHEDULED"
        assert audit["units_tested"] is None
        assert audit["failure_rate"] is None
        assert audit["failure_reason"] is None
        assert audit["recorded_by_user_id"] is None

    def test_service_part_opens_active_and_an_uncovered_request_opens_backordered(
        self, family_with_platform
    ):
        """PRD §3.9: "The server derives `commitment_expires_year` as `last_production_year` plus `committed_availability_years`, and the part opens in `status` `ACTIVE` with `superseded_by_part_id` empty, `filled_request_count`, `substituted_request_count` and `backordered_request_count` all 0, and `fill_rate_pct` empty."

        PRD §3.9: "The request is minted in `BACKORDERED` and settles within the very same call when stock allows: if the part's `on_hand_qty` is at least `requested_quantity`, the request becomes `FILLED`, its `shipped_from_part_id` is set to the part it was requested from, and the part's `on_hand_qty` is reduced by `requested_quantity`."
        PRD §3.9: "If stock does not cover the request it stays `BACKORDERED` — there are no partial fills."
        PRD §3.9: "A request left `BACKORDERED` gets `promised_ship_date` equal to the clock date plus 21 days."

        Design: Corner/state_machines/initial_state_of_all_twelve_state_machines_on_creation
        """
        stocked_part = build_service_part(family_with_platform.platform_id)
        assert stocked_part["status"] == "ACTIVE"
        assert stocked_part["superseded_by_part_id"] is None
        assert stocked_part["filled_request_count"] == 0
        assert stocked_part["substituted_request_count"] == 0
        assert stocked_part["backordered_request_count"] == 0
        assert stocked_part["fill_rate_pct"] is None

        empty_part = build_service_part(
            family_with_platform.platform_id,
            part_number="PN-COIL-EMPTY",
            category="IGNITION_MODULE",
            on_hand_qty=0,
            committed_availability_years=10,
            last_production_year=2027,
        )
        request = raise_parts_request(
            empty_part["id"], requested_quantity=2, channel="DEALER"
        )

        assert request["status"] == "BACKORDERED"
        assert request["promised_ship_date"] == "2026-08-24"
        assert request["shipped_from_part_id"] is None

        settled_part = read_service_part(empty_part["id"])
        assert settled_part["on_hand_qty"] == 0
        assert settled_part["backordered_request_count"] == 1


class TestValidTransitionsOnTheHappyPath:
    """The declared happy-path transitions fire and nothing else moves."""

    def test_unit_release_and_passing_audit_leave_the_family_untouched(
        self, released_order_plant
    ):
        """PRD §3.7: "Releasing a unit to finished goods requires `build_state` `HOT_TESTED`, else `ERR_UNIT_STATE_INVALID`; `conformance_state` `CONFORMING`, else `ERR_UNIT_NONCONFORMING`; and a parent order whose status is `RELEASED` or `IN_PRODUCTION`."

        PRD §3.7: "The unit reaches the terminal `RELEASED` build state with `released_at` stamped from the clock, the order's `built_quantity` rises by 1 while `staged_quantity` falls by 1, and the unit joins the order's allocation pool."
        PRD §3.7: "For an ordinary unit the factor is 1.10, allowing a ten percent production allowance above the certified value."
        PRD §3.8: "`failure_rate` is `units_failed` divided by `units_tested`, rounded half up to 4 decimal places."
        PRD §3.8: "When neither holds the audit is `PASSED` with `failure_reason` left empty."
        PRD §3.8: "The recording operator is retained as `recorded_by_user_id` in every case."
        PRD §3.8: "A passing audit changes nothing outside its own row — in particular the family's status and its `cumulative_audit_failures` are untouched."

        Design: Corner/state_machines/audit_pass_and_unit_release_are_valid_transitions
        """
        scenario = released_order_plant
        build_and_release_unit(scenario, "SN-0001")
        audit = schedule_line_audit(scenario.build_order_id, audit_week="2026-09-14")

        second_unit = _stage_second_unit(scenario)
        record_torque(second_unit["id"])
        hot_test_unit(second_unit["id"])
        released = release_engine_unit(second_unit["id"])

        assert released["build_state"] == "RELEASED"
        assert released["conformance_state"] == "CONFORMING"
        assert released["hot_test_emission_threshold"] == pytest.approx(5.63, abs=0.01)
        assert is_iso8601_timestamp(released["released_at"])
        assert released["released_at"].startswith("2026-08-03T08:00:00")

        order = scenario.refresh_build_order()
        assert order["built_quantity"] == 2
        assert order["staged_quantity"] == 0
        assert order["status"] == "IN_PRODUCTION"
        assert order["held_reason"] is None

        recorded = record_line_audit(
            audit["id"],
            units_tested=2,
            units_failed=0,
            max_measured_emission_g_per_kwh=5.60,
        )
        assert recorded["status"] == "PASSED"
        assert recorded["failure_rate"] == pytest.approx(0.0000, abs=0.0001)
        assert recorded["failure_reason"] is None
        assert recorded["recorded_by_user_id"] == COMPLIANCE_OFFICER["X-User-ID"]

        family = scenario.refresh_family()
        assert family["status"] == "CERTIFIED"
        assert family["cumulative_audit_failures"] == 0
        assert scenario.refresh_platform()["certification_posture"] == "OPEN"


class TestOrderCompletionBubblesUp:
    """The parent order settles itself when its last child unit settles."""

    def test_last_released_unit_completes_the_order_and_closes_it_to_new_units(
        self, production_ready_plant
    ):
        """PRD §3.7: "When the release brings `built_quantity` up to the order's `planned_quantity`, the order transitions `IN_PRODUCTION → COMPLETED` in the same request; a `COMPLETED` order accepts no further units, though allocation runs remain permitted on it."

        PRD §3.7: "Staging is admitted only against an order whose status is `RELEASED` or `IN_PRODUCTION`; an order still `PLANNED`, or `HELD`, or already `COMPLETED`, refuses new units with `ERR_BUILD_ORDER_NOT_ACCEPTING_UNITS`."
        PRD §3.7: "Each of the two consumed lots has 1 added to `consumed_qty` and 1 subtracted from `remaining_qty`, per §2.11 — note that the bound machining run and its casting lot are not charged in this way; only the carburetor and ignition lots are consumed piecewise."
        PRD §3.8: "The allocation pool is exactly the order's `built_quantity` — units whose `build_state` is `RELEASED`."
        PRD §3.8: "When it is 1, that single unit goes to whichever bucket had the larger fractional part, and when the two fractional parts are equal the unit goes to the **dealer** bucket."

        Design: Corner/state_machines/all_planned_units_released_bubbles_order_to_completed
        """
        scenario = production_ready_plant
        order = plan_build_order(
            scenario.model_id, scenario.line_id, week_span=1, planned_quantity=1
        )
        scenario.build_order = validate_success(
            api_client.release_build_order(order["id"], PRODUCTION_PLANNER), 200
        )

        build_and_release_unit(scenario, "SN-0009")

        completed = scenario.refresh_build_order()
        assert completed["status"] == "COMPLETED"
        assert completed["built_quantity"] == 1
        assert completed["staged_quantity"] == 0

        refused = api_client.create_engine_unit(
            create_engine_unit_payload(
                scenario.build_order_id,
                scenario.machining_run_id,
                scenario.carburetor_lot_id,
                scenario.ignition_lot_id,
                "SN-0010",
            ),
            QUALITY_ENGINEER,
        )
        validate_error(refused, "ERR_BUILD_ORDER_NOT_ACCEPTING_UNITS", 409)

        units, units_meta = validate_paginated(
            api_client.list_engine_units(
                QUALITY_ENGINEER, params={"build_order_id": scenario.build_order_id}
            )
        )
        assert units_meta["total_count"] == 1
        assert [unit["serial_number"] for unit in units] == ["SN-0009"]

        allocated = run_allocations(
            scenario.build_order_id, build_order_version(scenario.build_order_id)
        )
        assert allocated["allocated_dealer_units"] == 1
        assert allocated["allocated_mass_retail_units"] == 0
        assert allocated["unallocated_units"] == 0
        assert allocated["status"] == "COMPLETED"

        lot = read_lot(scenario.carburetor_lot_id)
        assert lot["consumed_qty"] == 1
        assert lot["remaining_qty"] == 799


class TestUnitReleaseSideEffects:
    """Staging and release move counters rather than merely bumping them."""

    def test_staging_and_release_reconcile_order_counters_and_the_lot_ledger(
        self, released_order_plant
    ):
        """PRD §3.7: "The order's `staged_quantity` rises by 1, and the very first unit staged against a `RELEASED` order advances that order `RELEASED → IN_PRODUCTION`."

        PRD §3.7: "Each of the two consumed lots has 1 added to `consumed_qty` and 1 subtracted from `remaining_qty`, per §2.11 — note that the bound machining run and its casting lot are not charged in this way; only the carburetor and ignition lots are consumed piecewise."
        PRD §3.7: "The unit reaches the terminal `RELEASED` build state with `released_at` stamped from the clock, the order's `built_quantity` rises by 1 while `staged_quantity` falls by 1, and the unit joins the order's allocation pool."
        PRD §3.7: "Progress counters are always the plain counts they claim to be: `staged_quantity` is the number of the order's units whose `build_state` is `STAGED`, `ASSEMBLED` or `HOT_TESTED`, `built_quantity` is the number whose `build_state` is `RELEASED`, and a `CANCELLED` unit counts toward neither."
        PRD §3.8: "The allocation pool is exactly the order's `built_quantity` — units whose `build_state` is `RELEASED`."
        PRD §3.8: "Units still `STAGED`, `ASSEMBLED` or `HOT_TESTED`, units `CANCELLED`, and units belonging to any other order are all excluded."
        PRD §2.11: "On a component lot, the pieces released to the line are conserved: `accepted_qty` always equals `consumed_qty` plus `remaining_qty`."

        Design: Corner/state_machines/unit_release_side_effects_reconcile_order_and_lot_counters
        """
        scenario = released_order_plant

        first_unit = stage_engine_unit(scenario, "SN-0001")
        after_first_staging = scenario.refresh_build_order()
        assert after_first_staging["status"] == "IN_PRODUCTION"
        assert after_first_staging["staged_quantity"] == 1

        second_unit = _stage_second_unit(scenario)
        after_second_staging = scenario.refresh_build_order()
        assert after_second_staging["staged_quantity"] == 2
        assert after_second_staging["built_quantity"] == 0

        charged_lot = read_lot(scenario.carburetor_lot_id)
        assert charged_lot["consumed_qty"] == 2
        assert charged_lot["remaining_qty"] == 798

        record_torque(first_unit["id"])
        hot_test_unit(first_unit["id"])
        release_engine_unit(first_unit["id"])

        after_release = scenario.refresh_build_order()
        assert after_release["staged_quantity"] == 1
        assert after_release["built_quantity"] == 1

        allocated = run_allocations(
            scenario.build_order_id, build_order_version(scenario.build_order_id)
        )
        assert allocated["allocated_dealer_units"] == 1
        assert allocated["allocated_mass_retail_units"] == 0
        assert allocated["unallocated_units"] == 0
        assert allocated["status"] == "IN_PRODUCTION"
        assert read_engine_unit(second_unit["id"])["build_state"] == "STAGED"

        final_lot = read_lot(scenario.carburetor_lot_id)
        assert final_lot["accepted_qty"] == 800
        assert final_lot["consumed_qty"] + final_lot["remaining_qty"] == 800


class TestConformancePreconditions:
    """The conformance axis is checked independently of the build axis."""

    def test_nonconforming_and_conforming_units_are_refused_from_opposite_sides(
        self, released_order_plant
    ):
        """PRD §3.7: "`out_of_spec_fastener_count` is the number of readings whose `torque_nm` is strictly below the lower bound or strictly above the upper bound."

        PRD §3.7: "A platform specified at 22.0 Nm with a tolerance of 0.05 therefore accepts everything from 20.90 through 23.10 inclusive."
        PRD §3.7: "The unit's `build_state` advances `STAGED → ASSEMBLED` regardless of the count, and its `conformance_state` becomes `NONCONFORMING` when `out_of_spec_fastener_count` is greater than zero, or is left at `PENDING` when every fastener was in band."
        PRD §3.7: "It is admitted only when `build_state` is `ASSEMBLED`, else `ERR_UNIT_STATE_INVALID`, and only when `conformance_state` is `PENDING`, else `ERR_UNIT_NONCONFORMING` — a nonconforming unit must be reworked before it can be hot-tested, and a quarantined unit is refused outright."
        PRD §3.7: "A unit whose `build_state` is `ASSEMBLED` or `HOT_TESTED` and whose `conformance_state` is `NONCONFORMING` may be sent back to staging, provided its `rework_count` is still below 2; a third attempt is refused with `ERR_REWORK_LIMIT_EXCEEDED`."
        PRD §3.7: "Rework adds 1 to `rework_count`, steps `build_state` back to `STAGED`, resets `conformance_state` to `PENDING`, and clears `torque_readings`, `out_of_spec_fastener_count`, `measured_rpm`, `measured_emission_g_per_kwh` and `hot_test_emission_threshold` back to empty."
        PRD §3.7: "A unit whose `conformance_state` is not `NONCONFORMING` may not be reworked, and one whose `build_state` is outside `ASSEMBLED` and `HOT_TESTED` is refused on the state axis instead."

        Design: Corner/state_machines/conformance_preconditions_reject_release_and_rework
        """
        scenario = released_order_plant
        nonconforming_unit = stage_engine_unit(scenario, "SN-0001")
        record_torque(nonconforming_unit["id"], OUT_OF_BAND_TORQUE_READINGS)

        conforming_unit = _stage_second_unit(scenario)
        record_torque(conforming_unit["id"])
        hot_test_unit(conforming_unit["id"])

        after_bad_torque = read_engine_unit(nonconforming_unit["id"])
        assert after_bad_torque["build_state"] == "ASSEMBLED"
        assert after_bad_torque["conformance_state"] == "NONCONFORMING"
        assert after_bad_torque["out_of_spec_fastener_count"] == 1

        validate_error(
            api_client.hot_test_engine_unit(
                nonconforming_unit["id"], hot_test_payload(), QUALITY_ENGINEER
            ),
            "ERR_UNIT_NONCONFORMING",
            409,
        )
        assert read_engine_unit(nonconforming_unit["id"])["measured_rpm"] is None

        validate_error(
            api_client.rework_engine_unit(conforming_unit["id"], QUALITY_ENGINEER),
            "ERR_UNIT_NONCONFORMING",
            409,
        )
        untouched = read_engine_unit(conforming_unit["id"])
        assert untouched["rework_count"] == 0
        assert untouched["build_state"] == "HOT_TESTED"

        reworked = rework_engine_unit(nonconforming_unit["id"])
        assert reworked["build_state"] == "STAGED"
        assert reworked["conformance_state"] == "PENDING"
        assert reworked["rework_count"] == 1
        assert reworked["torque_readings"] is None
        assert reworked["out_of_spec_fastener_count"] is None

        order = scenario.refresh_build_order()
        assert order["built_quantity"] == 0
        assert order["staged_quantity"] == 2


class TestTriggersFromTheWrongBuildState:
    """Every trigger absent from a state's transition list is refused."""

    @pytest.mark.parametrize(
        "trigger_name",
        [
            "hot_test_from_staged",
            "release_from_staged",
            "rework_from_staged",
            "torque_record_from_hot_tested",
        ],
    )
    def test_trigger_outside_the_current_build_state_is_refused(
        self, released_order_plant, trigger_name
    ):
        """PRD §3.7: "It is admitted only when `build_state` is `ASSEMBLED`, else `ERR_UNIT_STATE_INVALID`, and only when `conformance_state` is `PENDING`, else `ERR_UNIT_NONCONFORMING` — a nonconforming unit must be reworked before it can be hot-tested, and a quarantined unit is refused outright."

        PRD §3.7: "Releasing a unit to finished goods requires `build_state` `HOT_TESTED`, else `ERR_UNIT_STATE_INVALID`; `conformance_state` `CONFORMING`, else `ERR_UNIT_NONCONFORMING`; and a parent order whose status is `RELEASED` or `IN_PRODUCTION`."
        PRD §3.7: "A unit whose `conformance_state` is not `NONCONFORMING` may not be reworked, and one whose `build_state` is outside `ASSEMBLED` and `HOT_TESTED` is refused on the state axis instead."
        PRD §3.7: "Recording torque is admitted only when the unit's `build_state` is `STAGED`, else `ERR_UNIT_STATE_INVALID`, and only when its `conformance_state` is `PENDING` or `NONCONFORMING`; a unit whose conformance has been moved to `QUARANTINED` cannot be advanced and is refused with `ERR_UNIT_NONCONFORMING`."

        Design: Corner/state_machines/unit_triggers_from_wrong_build_state_are_rejected
        """
        scenario = released_order_plant
        staged_unit = stage_engine_unit(scenario, "SN-0001")
        hot_tested_unit = _stage_second_unit(scenario)
        record_torque(hot_tested_unit["id"])
        hot_test_unit(hot_tested_unit["id"])

        triggers = {
            "hot_test_from_staged": lambda: api_client.hot_test_engine_unit(
                staged_unit["id"], hot_test_payload(), QUALITY_ENGINEER
            ),
            "release_from_staged": lambda: api_client.release_engine_unit(
                staged_unit["id"], QUALITY_ENGINEER
            ),
            "rework_from_staged": lambda: api_client.rework_engine_unit(
                staged_unit["id"], QUALITY_ENGINEER
            ),
            "torque_record_from_hot_tested": lambda: api_client.torque_record_engine_unit(
                hot_tested_unit["id"], torque_record_payload(), QUALITY_ENGINEER
            ),
        }

        validate_error(triggers[trigger_name](), "ERR_UNIT_STATE_INVALID", 409)

    def test_refused_triggers_leave_both_units_and_the_order_unchanged(
        self, released_order_plant
    ):
        """PRD §3.7: "Recording torque is admitted only when the unit's `build_state` is `STAGED`, else `ERR_UNIT_STATE_INVALID`, and only when its `conformance_state` is `PENDING` or `NONCONFORMING`; a unit whose conformance has been moved to `QUARANTINED` cannot be advanced and is refused with `ERR_UNIT_NONCONFORMING`."

        PRD §3.7: "Progress counters are always the plain counts they claim to be: `staged_quantity` is the number of the order's units whose `build_state` is `STAGED`, `ASSEMBLED` or `HOT_TESTED`, `built_quantity` is the number whose `build_state` is `RELEASED`, and a `CANCELLED` unit counts toward neither."
        PRD §2.8: "The rules are evaluated in a fixed order and **the first violated rule decides the response** — later rules are never reported."

        Design: Corner/state_machines/unit_triggers_from_wrong_build_state_are_rejected
        """
        scenario = released_order_plant
        staged_unit = stage_engine_unit(scenario, "SN-0001")
        hot_tested_unit = _stage_second_unit(scenario)
        record_torque(hot_tested_unit["id"])
        hot_test_unit(hot_tested_unit["id"])

        validate_error(
            api_client.hot_test_engine_unit(
                staged_unit["id"], hot_test_payload(), QUALITY_ENGINEER
            ),
            "ERR_UNIT_STATE_INVALID",
            409,
        )
        validate_error(
            api_client.release_engine_unit(staged_unit["id"], QUALITY_ENGINEER),
            "ERR_UNIT_STATE_INVALID",
            409,
        )
        validate_error(
            api_client.rework_engine_unit(staged_unit["id"], QUALITY_ENGINEER),
            "ERR_UNIT_STATE_INVALID",
            409,
        )
        validate_error(
            api_client.torque_record_engine_unit(
                hot_tested_unit["id"], torque_record_payload(), QUALITY_ENGINEER
            ),
            "ERR_UNIT_STATE_INVALID",
            409,
        )

        still_staged = read_engine_unit(staged_unit["id"])
        assert still_staged["build_state"] == "STAGED"
        assert still_staged["rework_count"] == 0

        still_hot_tested = read_engine_unit(hot_tested_unit["id"])
        assert still_hot_tested["build_state"] == "HOT_TESTED"
        assert still_hot_tested["measured_rpm"] == 3400
        assert len(still_hot_tested["torque_readings"]) == 4

        assert scenario.refresh_build_order()["built_quantity"] == 0


class TestReplayedTriggers:
    """No trigger in the plant is idempotent."""

    def test_replaying_every_settled_trigger_answers_that_entity_state_error(
        self, released_order_plant
    ):
        """PRD §3.2: "Submission for review is the `CertificationEngineer`'s last act on the family."

        PRD §3.1: "Any operation attempted against a family whose status does not admit it — and every operation on a `SUSPENDED` family — is refused with `ERR_FAMILY_STATE_INVALID`."
        PRD §3.2: "It is admitted only from `DURABILITY_COMPLETE`, and only when the family's `certified_emission_g_per_kwh` has actually been computed; the family advances to `SUBMITTED` and the submitting operator's identifier is retained as `submitted_by_user_id`."
        PRD §3.2: "Certification is the `ComplianceOfficer`'s act, and it is admitted only from `SUBMITTED`."
        PRD §3.2: "Only a run whose status is `SCHEDULED` may be completed; completing a run that is already `COMPLETED` is refused with `ERR_DURABILITY_TEST_STATE_INVALID`."
        PRD §3.4: "Only a lot whose status is `RECEIVED` may be inspected; anything else is refused with `ERR_LOT_STATE_INVALID`."
        PRD §3.5: "A run may be closed while its status is `OPEN` or `CAPABILITY_HOLD`; a run already `CLOSED` may not be closed again and the attempt is refused with `ERR_MACHINING_RUN_STATE_INVALID`."
        PRD §3.3: "Releasing a model for production is a `PlantAdmin` action, admitted when the model's status is `DRAFT` or `SUSPENDED`; releasing an already `RELEASED` model is refused with `ERR_MODEL_STATE_INVALID`."
        PRD §3.6: "The order must be in `PLANNED`; an order already `RELEASED`, `IN_PRODUCTION`, `HELD` or `COMPLETED` is refused with `ERR_BUILD_ORDER_NOT_PLANNED`."
        PRD §3.8: "Only a `SCHEDULED` audit may be recorded — one already `PASSED` or `FAILED` cannot be re-recorded and the attempt is refused with `ERR_AUDIT_STATE_INVALID`."
        PRD §3.7: "Releasing a unit to finished goods requires `build_state` `HOT_TESTED`, else `ERR_UNIT_STATE_INVALID`; `conformance_state` `CONFORMING`, else `ERR_UNIT_NONCONFORMING`; and a parent order whose status is `RELEASED` or `IN_PRODUCTION`."
        PRD §3.9: "The plant's parts-availability commitment must have actually run out: the logical clock's year must be **strictly greater** than the part's `commitment_expires_year`, so a part whose commitment expires in the current clock year cannot yet be retired, and the attempt is refused with `ERR_AVAILABILITY_COMMITMENT_ACTIVE`."

        Design: Corner/state_machines/repeat_triggers_on_settled_entities_are_rejected
        """
        scenario = released_order_plant
        first_unit = build_and_release_unit(scenario, "SN-0001")
        audit = schedule_line_audit(scenario.build_order_id, audit_week="2026-09-14")
        build_and_release_unit(scenario, "SN-0002")
        record_line_audit(
            audit["id"],
            units_tested=2,
            units_failed=0,
            max_measured_emission_g_per_kwh=5.60,
        )
        part = build_service_part(scenario.platform_id)

        family_version_before = read_family(scenario.family_id)["version"]

        validate_error(
            api_client.submit_certification_family(
                scenario.family_id, CERTIFICATION_ENGINEER
            ),
            "ERR_FAMILY_STATE_INVALID",
            409,
        )
        validate_error(
            api_client.certify_certification_family(
                scenario.family_id, COMPLIANCE_OFFICER
            ),
            "ERR_FAMILY_STATE_INVALID",
            409,
        )
        validate_error(
            api_client.complete_durability_test(
                scenario.durability_run["id"],
                complete_durability_test_payload(),
                CERTIFICATION_ENGINEER,
            ),
            "ERR_DURABILITY_TEST_STATE_INVALID",
            409,
        )
        validate_error(
            api_client.inspect_component_lot(
                scenario.carburetor_lot_id,
                inspect_component_lot_payload(0),
                QUALITY_ENGINEER,
            ),
            "ERR_LOT_STATE_INVALID",
            409,
        )
        validate_error(
            api_client.close_machining_run(
                scenario.machining_run_id, close_machining_run_payload(), QUALITY_ENGINEER
            ),
            "ERR_MACHINING_RUN_STATE_INVALID",
            409,
        )
        validate_error(
            api_client.release_product_model(scenario.model_id, PLANT_ADMIN),
            "ERR_MODEL_STATE_INVALID",
            409,
        )
        validate_error(
            api_client.release_build_order(scenario.build_order_id, PRODUCTION_PLANNER),
            "ERR_BUILD_ORDER_NOT_PLANNED",
            409,
        )
        validate_error(
            api_client.record_line_audit(
                audit["id"], record_line_audit_payload(), COMPLIANCE_OFFICER
            ),
            "ERR_AUDIT_STATE_INVALID",
            409,
        )
        validate_error(
            api_client.release_engine_unit(first_unit["id"], QUALITY_ENGINEER),
            "ERR_UNIT_STATE_INVALID",
            409,
        )
        validate_error(
            api_client.obsolete_service_part(part["id"], PLANT_ADMIN),
            "ERR_AVAILABILITY_COMMITMENT_ACTIVE",
            409,
        )

        assert read_family(scenario.family_id)["version"] == family_version_before
        lot = read_lot(scenario.carburetor_lot_id)
        assert lot["sample_size"] == 40
        assert lot["defect_ppm"] == 0
        assert scenario.refresh_build_order()["built_quantity"] == 2
        supplier = read_supplier_scorecard(scenario.suppliers["carburetor"]["id"])
        assert supplier["consecutive_accepted_lots"] == 1


class TestTerminalStateLockdown:
    """Terminality is enforced per entity, each keeping its terminal values."""

    def test_completed_orders_released_units_and_cancelled_units_refuse_further_triggers(
        self, production_ready_plant
    ):
        """PRD §3.6: "The order must be in `PLANNED`; an order already `RELEASED`, `IN_PRODUCTION`, `HELD` or `COMPLETED` is refused with `ERR_BUILD_ORDER_NOT_PLANNED`."

        PRD §3.7: "When the release brings `built_quantity` up to the order's `planned_quantity`, the order transitions `IN_PRODUCTION → COMPLETED` in the same request; a `COMPLETED` order accepts no further units, though allocation runs remain permitted on it."
        PRD §3.7: "A unit whose `conformance_state` is not `NONCONFORMING` may not be reworked, and one whose `build_state` is outside `ASSEMBLED` and `HOT_TESTED` is refused on the state axis instead."
        PRD §3.7: "A unit whose `build_state` is `STAGED`, `ASSEMBLED` or `HOT_TESTED` may be scrapped; a unit already `RELEASED` or `CANCELLED` is refused with `ERR_UNIT_STATE_INVALID`."
        PRD §3.7: "Cancellation moves `build_state` to the terminal `CANCELLED`, leaves `conformance_state` untouched, returns one piece to each of the carburetor and ignition lots by subtracting 1 from `consumed_qty` and adding 1 to `remaining_qty` on each, and subtracts 1 from the order's `staged_quantity`."
        PRD §3.7: "Recording torque is admitted only when the unit's `build_state` is `STAGED`, else `ERR_UNIT_STATE_INVALID`, and only when its `conformance_state` is `PENDING` or `NONCONFORMING`; a unit whose conformance has been moved to `QUARANTINED` cannot be advanced and is refused with `ERR_UNIT_NONCONFORMING`."
        PRD §3.5: "A run may be closed while its status is `OPEN` or `CAPABILITY_HOLD`; a run already `CLOSED` may not be closed again and the attempt is refused with `ERR_MACHINING_RUN_STATE_INVALID`."
        PRD §3.2: "Only a run whose status is `SCHEDULED` may be completed; completing a run that is already `COMPLETED` is refused with `ERR_DURABILITY_TEST_STATE_INVALID`."

        Design: Corner/state_machines/terminal_states_refuse_every_further_trigger
        """
        scenario = production_ready_plant
        solo_order = plan_build_order(
            scenario.model_id, scenario.line_id, week_span=1, planned_quantity=1
        )
        scenario.build_order = validate_success(
            api_client.release_build_order(solo_order["id"], PRODUCTION_PLANNER), 200
        )
        released_unit = build_and_release_unit(scenario, "SN-0009")
        completed_order_id = scenario.build_order_id

        second_order = plan_build_order(scenario.model_id, scenario.line_id)
        scenario.build_order = validate_success(
            api_client.release_build_order(second_order["id"], PRODUCTION_PLANNER), 200
        )
        cancelled_unit = stage_engine_unit(scenario, "SN-0002")
        cancel_engine_unit(cancelled_unit["id"])

        validate_error(
            api_client.release_build_order(completed_order_id, PRODUCTION_PLANNER),
            "ERR_BUILD_ORDER_NOT_PLANNED",
            409,
        )
        assert read_build_order(completed_order_id)["built_quantity"] == 1

        validate_error(
            api_client.rework_engine_unit(released_unit["id"], QUALITY_ENGINEER),
            "ERR_UNIT_STATE_INVALID",
            409,
        )
        validate_error(
            api_client.cancel_engine_unit(released_unit["id"], QUALITY_ENGINEER),
            "ERR_UNIT_STATE_INVALID",
            409,
        )
        still_released = read_engine_unit(released_unit["id"])
        assert still_released["build_state"] == "RELEASED"
        assert still_released["conformance_state"] == "CONFORMING"
        assert still_released["released_at"] == released_unit["released_at"]

        validate_error(
            api_client.torque_record_engine_unit(
                cancelled_unit["id"], torque_record_payload(), QUALITY_ENGINEER
            ),
            "ERR_UNIT_STATE_INVALID",
            409,
        )
        assert read_engine_unit(cancelled_unit["id"])["build_state"] == "CANCELLED"
        lot = read_lot(scenario.carburetor_lot_id)
        assert lot["consumed_qty"] == 1
        assert lot["remaining_qty"] == 799

        validate_error(
            api_client.close_machining_run(
                scenario.machining_run_id, close_machining_run_payload(), QUALITY_ENGINEER
            ),
            "ERR_MACHINING_RUN_STATE_INVALID",
            409,
        )
        assert read_machining_run(scenario.machining_run_id)["status"] == "CLOSED"

        validate_error(
            api_client.complete_durability_test(
                scenario.durability_run["id"],
                complete_durability_test_payload(),
                CERTIFICATION_ENGINEER,
            ),
            "ERR_DURABILITY_TEST_STATE_INVALID",
            409,
        )
        settled_run = read_durability_run(scenario.durability_run["id"])
        assert settled_run["status"] == "COMPLETED"
        assert settled_run["computed_deterioration_factor"] == pytest.approx(
            1.2800, abs=0.0001
        )


class TestReworkCycleBound:
    """The rework loop is closed but bounded by a strict counter."""

    def test_two_rework_passes_are_accepted_and_the_third_is_refused(
        self, released_order_plant
    ):
        """PRD §3.7: "A unit whose `build_state` is `ASSEMBLED` or `HOT_TESTED` and whose `conformance_state` is `NONCONFORMING` may be sent back to staging, provided its `rework_count` is still below 2; a third attempt is refused with `ERR_REWORK_LIMIT_EXCEEDED`."

        PRD §3.7: "Rework adds 1 to `rework_count`, steps `build_state` back to `STAGED`, resets `conformance_state` to `PENDING`, and clears `torque_readings`, `out_of_spec_fastener_count`, `measured_rpm`, `measured_emission_g_per_kwh` and `hot_test_emission_threshold` back to empty."
        PRD §3.7: "As §2.11 states, component consumption is not re-charged — the engine keeps its original lots, so a unit can travel `PENDING → NONCONFORMING → PENDING` twice without consuming a single extra piece."
        PRD §3.7: "Progress counters are always the plain counts they claim to be: `staged_quantity` is the number of the order's units whose `build_state` is `STAGED`, `ASSEMBLED` or `HOT_TESTED`, `built_quantity` is the number whose `build_state` is `RELEASED`, and a `CANCELLED` unit counts toward neither."

        Design: Corner/state_machines/rework_cycle_is_bounded_by_max_rework_cycles
        """
        scenario = released_order_plant
        unit = stage_engine_unit(scenario, "SN-0001")

        record_torque(unit["id"], OUT_OF_BAND_TORQUE_READINGS)
        first_pass = rework_engine_unit(unit["id"])
        assert first_pass["build_state"] == "STAGED"
        assert first_pass["conformance_state"] == "PENDING"
        assert first_pass["rework_count"] == 1

        record_torque(unit["id"], OUT_OF_BAND_TORQUE_READINGS)
        second_pass = rework_engine_unit(unit["id"])
        assert second_pass["rework_count"] == 2

        record_torque(unit["id"], OUT_OF_BAND_TORQUE_READINGS)
        validate_error(
            api_client.rework_engine_unit(unit["id"], QUALITY_ENGINEER),
            "ERR_REWORK_LIMIT_EXCEEDED",
            409,
        )

        bounded = read_engine_unit(unit["id"])
        assert bounded["build_state"] == "ASSEMBLED"
        assert bounded["conformance_state"] == "NONCONFORMING"
        assert bounded["rework_count"] == 2

        lot = read_lot(scenario.carburetor_lot_id)
        assert lot["consumed_qty"] == 1
        assert lot["remaining_qty"] == 799

        order = scenario.refresh_build_order()
        assert order["staged_quantity"] == 1
        assert order["built_quantity"] == 0


class TestSupplierInspectionLadder:
    """Each acceptance syncs the ledger, and the ladder re-plans the next lot."""

    def test_accepted_streak_walks_the_inspection_level_down_the_ladder(
        self, canonical_clock
    ):
        """PRD §3.4: "The supplier's current `incoming_inspection_level` is snapshotted onto the lot as `inspection_level_at_receipt`, and both `sample_size` and `acceptance_number` are computed from that snapshot."

        PRD §3.4: "At `SKIP_LOT` the sample size is 0 — the lot is waved through without inspection."
        PRD §3.4: "At `REDUCED` it is the larger of 5 pieces and two percent of `lot_quantity` rounded up to the next whole piece."
        PRD §3.4: "At `NORMAL` it is the larger of 8 pieces and five percent of `lot_quantity` rounded up."
        PRD §3.4: "The acceptance number — the maximum number of defective pieces in the sample that still permits acceptance — is 0 for a `CRITICAL` supplier, and for a `MAJOR` supplier it is ten percent of the resulting sample size rounded **down** to a whole number."
        PRD §3.4: "An acceptance sets `accepted_qty` to `lot_quantity` minus `defects_found`, sets `remaining_qty` equal to that `accepted_qty`, writes the lot's own `defect_ppm`, records the inspecting operator as `inspected_by_user_id`, adds 1 to the supplier's `inspected_lot_count`, adds 1 to the supplier's `consecutive_accepted_lots`, and recomputes the supplier's `rolling_defect_ppm`."
        PRD §3.4: "Otherwise: if the recomputed pooled rate is **greater than** 100,000 parts per million, the supplier becomes `SUSPENDED` and its `incoming_inspection_level` becomes `TIGHTENED`; else if the pooled rate is **greater than** 25,000 parts per million, the supplier becomes `PROBATION` and its level becomes `TIGHTENED`; else the supplier becomes `APPROVED` and its level is chosen from the accepted-lot streak — `SKIP_LOT` when `consecutive_accepted_lots` is at least 5, `REDUCED` when it is at least 3, and `NORMAL` otherwise."
        PRD §3.4: "The supplier's `criticality` follows from that category and is never supplied: a `CASTING` supplier is `CRITICAL`, and a `CARBURETOR` or `IGNITION` supplier is `MAJOR`."
        PRD §3.4: "Only the pooled figure gates anything: the scorecard read returns `supplier_id`, `rolling_defect_ppm`, `scorecard_average_ppm`, `inspected_lot_count`, `consecutive_accepted_lots`, `approval_status`, `incoming_inspection_level` and `criticality`, and changes nothing."

        Design: Corner/state_machines/supplier_inspection_ladder_ledger_sync_after_accepted_streak
        """
        supplier = build_supplier(
            supplier_code="SUP-CARB",
            name="Kirin Carburetor Works",
            component_category="CARBURETOR",
        )

        first_lot = receive_component_lot(
            supplier["id"], lot_code="CB-001", lot_quantity=800
        )
        assert first_lot["sample_size"] == 40
        assert first_lot["acceptance_number"] == 4
        inspect_component_lot(first_lot["id"], 0)

        second_lot = receive_component_lot(
            supplier["id"], lot_code="CB-002", lot_quantity=600
        )
        assert second_lot["sample_size"] == 30
        assert second_lot["acceptance_number"] == 3
        inspect_component_lot(second_lot["id"], 0)

        third_lot = receive_component_lot(
            supplier["id"], lot_code="CB-003", lot_quantity=400
        )
        assert third_lot["sample_size"] == 20
        assert third_lot["acceptance_number"] == 2
        inspect_component_lot(third_lot["id"], 0)

        after_third = read_supplier_scorecard(supplier["id"])
        assert after_third["consecutive_accepted_lots"] == 3
        assert after_third["incoming_inspection_level"] == "REDUCED"

        fourth_lot = receive_component_lot(
            supplier["id"], lot_code="CB-004", lot_quantity=800
        )
        assert fourth_lot["inspection_level_at_receipt"] == "REDUCED"
        assert fourth_lot["sample_size"] == 16
        assert fourth_lot["acceptance_number"] == 1
        inspect_component_lot(fourth_lot["id"], 0)

        fifth_lot = receive_component_lot(
            supplier["id"], lot_code="CB-005", lot_quantity=800
        )
        inspect_component_lot(fifth_lot["id"], 0)

        after_fifth = read_supplier_scorecard(supplier["id"])
        assert after_fifth["consecutive_accepted_lots"] == 5
        assert after_fifth["incoming_inspection_level"] == "SKIP_LOT"

        sixth_lot = receive_component_lot(
            supplier["id"], lot_code="CB-006", lot_quantity=800
        )
        assert sixth_lot["inspection_level_at_receipt"] == "SKIP_LOT"
        assert sixth_lot["sample_size"] == 0
        assert sixth_lot["acceptance_number"] == 0
        settled_sixth = inspect_component_lot(sixth_lot["id"], 0)
        assert settled_sixth["status"] == "ACCEPTED"
        assert settled_sixth["accepted_qty"] == 800

        scorecard = validate_success(
            api_client.get_supplier_scorecard(supplier["id"], QUALITY_ENGINEER), 200
        )
        assert scorecard["inspected_lot_count"] == 6
        assert scorecard["consecutive_accepted_lots"] == 6
        assert scorecard["rolling_defect_ppm"] == 0
        assert scorecard["scorecard_average_ppm"] == 0
        assert scorecard["approval_status"] == "APPROVED"
        assert scorecard["incoming_inspection_level"] == "SKIP_LOT"
        assert scorecard["criticality"] == "MAJOR"
