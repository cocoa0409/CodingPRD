"""Which rule speaks first, and what happens exactly on a gate.

Two families of check live here. The first pits two genuinely violated rules
against each other and pins which one the response reports. The second walks a
metric onto the exact value of its gate and one step past it.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    build_and_release_unit,
    build_and_release_units,
    build_assembly_line,
    build_certification_family,
    build_certified_family_and_platform,
    build_engine_platform,
    build_order_version,
    build_product_model,
    build_released_order_plant,
    build_safety_certification,
    build_supplier,
    close_machining_run,
    create_build_order_payload,
    create_engine_unit_payload,
    inspect_component_lot,
    open_machining_run,
    plan_build_order,
    read_build_order,
    read_engine_unit,
    read_family,
    read_lot,
    read_machining_run,
    read_platform,
    receive_component_lot,
    record_line_audit,
    record_torque,
    release_product_model,
    run_allocations_payload,
    schedule_line_audit,
    set_clock,
    stage_engine_unit,
    torque_readings_at,
    validate_error,
)

PLANT_ADMIN = TEST_USERS["plant_admin_headers"]
QUALITY_ENGINEER = TEST_USERS["quality_engineer_headers"]
PRODUCTION_PLANNER = TEST_USERS["production_planner_headers"]

SINGLE_UNIT_ORDER = {"planned_quantity": 1, "week_span": 1}
EDGE_READINGS = torque_readings_at(20.90, 23.10, 22.0, 22.0)
JUST_OUTSIDE_READINGS = torque_readings_at(20.89, 23.11, 22.0, 22.0)
GATE_MEASUREMENTS = [65.00500, 64.99500, 65.00500, 64.99500, 65.00000]


def _uncertified_platform_with_a_released_model(expires_on):
    """A model released off a DRAFT family, so posture is still PENDING."""
    family = build_certification_family()
    platform = build_engine_platform(family["id"])
    assert read_platform(platform["id"])["certification_posture"] == "PENDING"
    model = build_product_model(platform["id"], model_code="WM-P1-MOWER")
    build_safety_certification(model["id"], expires_on=expires_on)
    release_product_model(model["id"])
    line = build_assembly_line()
    order = plan_build_order(
        model["id"], line["id"], week_span=1, planned_quantity=4
    )
    return platform, model, order


def _order_holding_its_only_unit():
    """A one-unit order whose single unit is staged, so the quota is exhausted."""
    scenario = build_released_order_plant(order_overrides=SINGLE_UNIT_ORDER)
    stage_engine_unit(scenario, "SN-R-01")
    return scenario


def _stage_attempt(scenario, serial_number, carburetor_lot_id=None):
    return api_client.create_engine_unit(
        create_engine_unit_payload(
            scenario.build_order_id,
            scenario.machining_run_id,
            carburetor_lot_id or scenario.carburetor_lot_id,
            scenario.ignition_lot_id,
            serial_number,
        ),
        QUALITY_ENGINEER,
    )


def _line_with_a_walk_mower_week_booked():
    """A shared line already carrying a walk-mower order in week 2026-09-21."""
    scenario = build_certified_family_and_platform()
    walk_model = build_product_model(scenario.platform_id)
    build_safety_certification(walk_model["id"])
    release_product_model(walk_model["id"])
    line = build_assembly_line(
        supported_product_lines=["WALK_MOWER", "SNOW_THROWER"],
        weekly_capacity_units=500,
        changeover_gap_weeks=1,
    )
    walk_order = plan_build_order(
        walk_model["id"],
        line["id"],
        production_week="2026-09-21",
        week_span=1,
        planned_quantity=1,
    )
    snow_model = build_product_model(
        scenario.platform_id,
        model_code="SN-P4-THROWER",
        product_line="SNOW_THROWER",
        blade_brake_type="ENGINE_KILL",
        operator_presence_type="TWO_HAND",
        standard_cost_cents=33000,
        msrp_cents=89900,
        dealer_share_pct=0.60,
        dealer_cap_units=800,
        mass_retail_cap_units=800,
    )
    build_safety_certification(snow_model["id"], standard_code="ANSI_B71_3")
    release_product_model(snow_model["id"])
    return line, walk_order, snow_model


def _plan_attempt(model_id, line_id, production_week, planned_quantity):
    return api_client.create_build_order(
        create_build_order_payload(
            model_id,
            line_id,
            production_week=production_week,
            week_span=1,
            planned_quantity=planned_quantity,
        ),
        PRODUCTION_PLANNER,
    )


def _two_accepted_casting_lots():
    supplier = build_supplier(
        supplier_code="SUP-CAST",
        name="Foundry Nord Castings",
        component_category="CASTING",
    )
    lots = []
    for lot_code in ("CS-001", "CS-002"):
        lot = receive_component_lot(supplier["id"], lot_code=lot_code)
        lots.append(inspect_component_lot(lot["id"], defects_found=0))
    return lots


class TestSafetyOutranksPlatformPosture:
    """A lapsed bench test speaks before an uncertified emission family."""

    def test_an_expired_certification_is_reported_before_a_pending_posture(
        self, canonical_clock
    ):
        """PRD §2.8: "The rules are evaluated in a fixed order and **the first violated rule decides the response** — later rules are never reported."
        PRD §3.6: "The model's latest passing safety certification must exist and must still be valid at the clock date, else `ERR_SAFETY_CERTIFICATION_MISSING` or `ERR_SAFETY_CERTIFICATION_EXPIRED` respectively, selected and compared exactly as in §3.3."
        PRD §3.6: "And the model's platform must carry `certification_posture` `OPEN`, else `ERR_FAMILY_NOT_CERTIFIED`."

        Design: Difficulty/priority_pair_validation_conflict/expired_safety_certification_outranks_uncertified_platform
        """
        platform, model, order = _uncertified_platform_with_a_released_model(
            expires_on="2026-08-10"
        )
        set_clock("2026-08-20T08:00:00Z")

        response = api_client.release_build_order(order["id"], PRODUCTION_PLANNER)

        validate_error(response, ApiErrorId.ERR_SAFETY_CERTIFICATION_EXPIRED.value)

        stored = read_build_order(order["id"])
        assert stored["status"] == "PLANNED"
        assert stored["released_at"] is None
        # The unreported violation is real all the same.
        assert read_platform(platform["id"])["certification_posture"] == "PENDING"

    def test_the_posture_refusal_surfaces_only_once_the_certification_is_valid(
        self, canonical_clock
    ):
        """PRD §3.6: "And the model's platform must carry `certification_posture` `OPEN`, else `ERR_FAMILY_NOT_CERTIFIED`."
        PRD §2.7: "Only a platform whose posture is `OPEN` may have production released against it."
        PRD §3.3: "If one exists but its `expires_on` is earlier than the logical clock's date, the release is refused with `ERR_SAFETY_CERTIFICATION_EXPIRED`; an `expires_on` equal to the clock date still counts as valid."

        Design: Difficulty/priority_pair_validation_conflict/expired_safety_certification_outranks_uncertified_platform
        """
        platform, _, order = _uncertified_platform_with_a_released_model(
            expires_on="2027-07-15"
        )
        set_clock("2026-08-20T08:00:00Z")

        response = api_client.release_build_order(order["id"], PRODUCTION_PLANNER)

        validate_error(response, ApiErrorId.ERR_FAMILY_NOT_CERTIFIED.value)
        assert read_build_order(order["id"])["status"] == "PLANNED"
        assert read_platform(platform["id"])["certification_posture"] == "PENDING"


class TestOrderStateOutranksQuantityQuota:
    """A finished order refuses units on its state, not on its arithmetic."""

    def test_a_completed_order_refuses_the_next_unit_on_its_state(
        self, canonical_clock
    ):
        """PRD §3.7: "Staging is admitted only against an order whose status is `RELEASED` or `IN_PRODUCTION`; an order still `PLANNED`, or `HELD`, or already `COMPLETED`, refuses new units with `ERR_BUILD_ORDER_NOT_ACCEPTING_UNITS`."
        PRD §3.7: "When the release brings `built_quantity` up to the order's `planned_quantity`, the order transitions `IN_PRODUCTION → COMPLETED` in the same request; a `COMPLETED` order accepts no further units, though allocation runs remain permitted on it."
        PRD §3.7: "Then two quota checks: staging one more unit must not push the order's `staged_quantity` plus `built_quantity` past its `planned_quantity`, else `ERR_BUILD_ORDER_QUANTITY_EXCEEDED`; and each consumed lot must have `remaining_qty` of at least 1, else `ERR_COMPONENT_LOT_DEPLETED`."

        Design: Difficulty/priority_pair_validation_conflict/completed_order_state_outranks_quantity_quota
        """
        scenario = build_released_order_plant(order_overrides=SINGLE_UNIT_ORDER)
        build_and_release_unit(scenario, "SN-Q-01")

        order = read_build_order(scenario.build_order_id)
        assert order["status"] == "COMPLETED"
        assert order["built_quantity"] == 1
        assert order["staged_quantity"] == 0

        # staged 0 + built 1 + 1 = 2 exceeds the planned 1, so the quota is live too.
        response = _stage_attempt(scenario, "SN-Q-02")

        validate_error(response, ApiErrorId.ERR_BUILD_ORDER_NOT_ACCEPTING_UNITS.value)

    def test_the_refused_staging_charges_nothing_to_the_order_or_the_lots(
        self, canonical_clock
    ):
        """PRD §2.11: "Staging an engine unit charges one piece to each of the two lots it consumes, adding 1 to each lot's `consumed_qty` and subtracting 1 from each lot's `remaining_qty`."
        PRD §2.11: "On a component lot, the pieces released to the line are conserved: `accepted_qty` always equals `consumed_qty` plus `remaining_qty`."

        Design: Difficulty/priority_pair_validation_conflict/completed_order_state_outranks_quantity_quota
        """
        scenario = build_released_order_plant(order_overrides=SINGLE_UNIT_ORDER)
        build_and_release_unit(scenario, "SN-Q-01")

        _stage_attempt(scenario, "SN-Q-02")

        lot = read_lot(scenario.carburetor_lot_id)
        assert lot["consumed_qty"] == 1
        assert lot["remaining_qty"] == 799
        assert lot["accepted_qty"] == lot["consumed_qty"] + lot["remaining_qty"]

        units = api_client.list_engine_units(
            QUALITY_ENGINEER, params={"build_order_id": scenario.build_order_id}
        )
        serials = [row["serial_number"] for row in units.json()["data"]]
        assert serials == ["SN-Q-01"]


class TestLotReleasabilityOutranksQuantityQuota:
    """An unreleasable lot speaks before the order's own quota."""

    def test_a_rejected_lot_is_reported_before_the_exhausted_quota(
        self, canonical_clock
    ):
        """PRD §3.7: "Each consumed lot's status must be `ACCEPTED` or `DEVIATION_ACCEPTED`, else `ERR_COMPONENT_LOT_NOT_RELEASABLE`."
        PRD §2.8: "Likewise, staging a unit against a lot that is both quarantined and depleted answers `ERR_COMPONENT_LOT_NOT_RELEASABLE`, because a safety rule outranks a quota rule."

        Design: Difficulty/priority_pair_validation_conflict/rejected_lot_safety_outranks_quantity_quota
        """
        scenario = _order_holding_its_only_unit()
        second_lot = receive_component_lot(
            scenario.suppliers["carburetor"]["id"], lot_code="CB-002", lot_quantity=200
        )
        rejected = inspect_component_lot(second_lot["id"], defects_found=2)
        assert rejected["status"] == "REJECTED"
        assert rejected["remaining_qty"] == 0

        response = _stage_attempt(
            scenario, "SN-R-02", carburetor_lot_id=second_lot["id"]
        )

        validate_error(response, ApiErrorId.ERR_COMPONENT_LOT_NOT_RELEASABLE.value)

        order = read_build_order(scenario.build_order_id)
        assert order["staged_quantity"] == 1
        assert order["built_quantity"] == 0
        assert order["status"] == "IN_PRODUCTION"

    def test_the_quota_refusal_surfaces_when_every_lot_is_releasable(
        self, canonical_clock
    ):
        """PRD §3.7: "Then two quota checks: staging one more unit must not push the order's `staged_quantity` plus `built_quantity` past its `planned_quantity`, else `ERR_BUILD_ORDER_QUANTITY_EXCEEDED`; and each consumed lot must have `remaining_qty` of at least 1, else `ERR_COMPONENT_LOT_DEPLETED`."
        PRD §2.8: "**Capacity and quota, evaluated last**, in this order: line weekly capacity (`ERR_LINE_CAPACITY_EXCEEDED`), build order quantity (`ERR_BUILD_ORDER_QUANTITY_EXCEEDED`), lot depletion (`ERR_COMPONENT_LOT_DEPLETED`), empty allocation pool (`ERR_NO_ALLOCATABLE_UNITS`)."

        Design: Difficulty/priority_pair_validation_conflict/rejected_lot_safety_outranks_quantity_quota
        """
        scenario = _order_holding_its_only_unit()
        assert read_lot(scenario.carburetor_lot_id)["status"] == "ACCEPTED"

        response = _stage_attempt(scenario, "SN-R-02")

        validate_error(response, ApiErrorId.ERR_BUILD_ORDER_QUANTITY_EXCEEDED.value)
        assert read_build_order(scenario.build_order_id)["staged_quantity"] == 1


class TestChangeoverOutranksLineCapacity:
    """Retooling time is checked before the weekly load."""

    def test_the_changeover_conflict_is_reported_before_the_capacity_breach(
        self, canonical_clock
    ):
        """PRD §3.6: "If any other build order whose status is `PLANNED`, `RELEASED` or `IN_PRODUCTION` sits on the same assembly line, is for a **different** `product_line`, and occupies a week that lies within `changeover_gap_weeks` whole weeks of any week this order would occupy, the plan is refused with `ERR_LINE_CHANGEOVER_CONFLICT`."
        PRD §3.6: "Capacity is checked last, and it is checked per week rather than in aggregate."
        PRD §3.6: "An order spreads its `planned_quantity` evenly across its span, contributing to each occupied week a load of `planned_quantity` divided by `week_span`, rounded **up** to a whole unit."

        Design: Difficulty/priority_pair_validation_conflict/changeover_conflict_outranks_line_capacity
        """
        line, walk_order, snow_model = _line_with_a_walk_mower_week_booked()

        # One week away from the booked walk-mower week and 1000 units into a
        # 500-unit week: both rules are violated by the same request.
        response = _plan_attempt(snow_model["id"], line["id"], "2026-09-28", 1000)

        validate_error(response, ApiErrorId.ERR_LINE_CHANGEOVER_CONFLICT.value)

        assert read_build_order(walk_order["id"])["status"] == "PLANNED"
        orders = api_client.list_build_orders(
            PRODUCTION_PLANNER, params={"assembly_line_id": line["id"]}
        )
        assert orders.json()["meta"]["total_count"] == 1

    def test_the_capacity_breach_surfaces_once_the_changeover_gap_is_respected(
        self, canonical_clock
    ):
        """PRD §3.6: "For every week this order would occupy, the sum of that per-week load over all orders on the same line and in the same week whose status is `PLANNED`, `RELEASED` or `IN_PRODUCTION` — this order included — must be at most the line's `weekly_capacity_units`."
        PRD §3.6: "A breach in even one occupied week refuses the whole plan with `ERR_LINE_CAPACITY_EXCEEDED`."
        PRD §3.6: "The changeover gap is the minimum whole-week separation the line requires between orders of *different* product lines — the time it takes to retool."

        Design: Difficulty/priority_pair_validation_conflict/changeover_conflict_outranks_line_capacity
        """
        line, walk_order, snow_model = _line_with_a_walk_mower_week_booked()

        # Two whole weeks clear of the walk-mower week, so only the load is wrong.
        response = _plan_attempt(snow_model["id"], line["id"], "2026-10-05", 1000)

        validate_error(response, ApiErrorId.ERR_LINE_CAPACITY_EXCEEDED.value)
        assert read_build_order(walk_order["id"])["status"] == "PLANNED"


class TestCapabilityIndexAtTheCriticalGate:
    """The capability gate is inclusive, and the index is rounded first."""

    def test_a_capability_index_landing_exactly_on_the_gate_closes_the_run(
        self, canonical_clock
    ):
        """PRD §3.5: "`sigma_mm` is the sample standard deviation computed with the **n minus 1** divisor — that is, the square root of the sum of the squared deviations of each reading from the mean, divided by one less than the number of readings — rounded half up to 6 decimal places."
        PRD §3.5: "The capability index `cpk` is then the smaller of two distances, the upper limit minus the mean and the mean minus the lower limit, divided by three times `sigma_mm`, rounded half up to 4 decimal places."
        PRD §3.5: "Clearing the gate moves the run to `CLOSED`, and only a `CLOSED` run may supply the critical component of an engine unit."

        Design: Difficulty/boundary_precision_check/cpk_exactly_at_critical_capability_gate
        """
        family = build_certification_family()
        platform = build_engine_platform(family["id"])
        casting_lot = _two_accepted_casting_lots()[0]
        run = open_machining_run(
            platform["id"],
            casting_lot["id"],
            component_type="CYLINDER_BORE",
            lsl_mm=64.98005,
            usl_mm=65.01995,
        )
        assert run["criticality"] == "CRITICAL"

        closed = close_machining_run(run["id"], GATE_MEASUREMENTS)

        assert closed["sample_count"] == 5
        assert closed["mean_mm"] == pytest.approx(65.000000, abs=0.0000005)
        assert closed["sigma_mm"] == pytest.approx(0.005000, abs=0.0000005)
        assert closed["cpk"] == pytest.approx(1.3300, abs=0.00005)
        assert closed["status"] == "CLOSED"
        assert closed["closed_at"].startswith("2026-08-03T08:00:00")

    def test_a_window_tighter_by_fifteen_hundred_thousandths_holds_the_run(
        self, canonical_clock
    ):
        """PRD §3.5: "The run then forks on the **rounded** `cpk` against the gate its criticality demands: 1.33 for a `CRITICAL` run and 1.00 for a `MAJOR` run."
        PRD §3.5: "The comparison is inclusive at the gate, so a `MAJOR` run landing on exactly 1.0000 clears."
        PRD §3.5: "Missing the gate moves the run to `CAPABILITY_HOLD`; the capability figures are written either way, and `closed_at` is stamped from the clock on either outcome."

        Design: Difficulty/boundary_precision_check/cpk_exactly_at_critical_capability_gate
        """
        family = build_certification_family()
        platform = build_engine_platform(family["id"])
        first_lot, second_lot = _two_accepted_casting_lots()
        at_the_gate = open_machining_run(
            platform["id"],
            first_lot["id"],
            component_type="CYLINDER_BORE",
            lsl_mm=64.98005,
            usl_mm=65.01995,
        )
        below_the_gate = open_machining_run(
            platform["id"],
            second_lot["id"],
            component_type="CYLINDER_BORE",
            lsl_mm=64.98020,
            usl_mm=65.01980,
        )

        close_machining_run(at_the_gate["id"], GATE_MEASUREMENTS)
        held = close_machining_run(below_the_gate["id"], GATE_MEASUREMENTS)

        assert held["cpk"] == pytest.approx(1.3200, abs=0.00005)
        assert held["status"] == "CAPABILITY_HOLD"
        assert held["closed_at"].startswith("2026-08-03T08:00:00")

        # Identical statistics; only the narrower window flips the outcome.
        cleared = read_machining_run(at_the_gate["id"])
        assert held["mean_mm"] == pytest.approx(cleared["mean_mm"], abs=0.0000005)
        assert held["sigma_mm"] == pytest.approx(cleared["sigma_mm"], abs=0.0000005)
        assert cleared["status"] == "CLOSED"


class TestAuditRateAtTheQuarterThreshold:
    """The rate gate is strict, so exactly a quarter passes."""

    def test_one_failure_in_four_sits_on_the_gate_and_passes(self, canonical_clock):
        """PRD §3.8: "A **rate breach** occurs when `failure_rate` is strictly greater than 0.25; the gate being strict matters, so one failure in four tested — a rate of 0.2500 — passes, while two in four fails."
        PRD §3.8: "When neither holds the audit is `PASSED` with `failure_reason` left empty."
        PRD §3.8: "A passing audit changes nothing outside its own row — in particular the family's status and its `cumulative_audit_failures` are untouched."

        Design: Difficulty/boundary_precision_check/audit_failure_rate_exactly_at_quarter_threshold
        """
        scenario = build_released_order_plant()
        build_and_release_units(scenario, 4)
        audit = schedule_line_audit(scenario.build_order_id, audit_week="2026-09-14")
        assert audit["required_sample_size"] == 2

        recorded = record_line_audit(
            audit["id"],
            units_tested=4,
            units_failed=1,
            max_measured_emission_g_per_kwh=5.60,
        )

        assert recorded["failure_rate"] == pytest.approx(0.2500, abs=0.00005)
        assert recorded["status"] == "PASSED"
        assert recorded["failure_reason"] is None

        family = read_family(scenario.family_id)
        assert family["status"] == "CERTIFIED"
        assert family["cumulative_audit_failures"] == 0

    def test_two_failures_in_four_cross_the_gate_and_hold_the_family(
        self, canonical_clock
    ):
        """PRD §3.8: "Otherwise, when a rate breach holds, the audit is `FAILED` with `failure_reason` `FAILURE_RATE_EXCEEDED`."
        PRD §3.8: "An **emission breach** occurs when `max_measured_emission_g_per_kwh` is strictly greater than the `family_emission_limit_g_per_kwh` of the family snapshotted on the audit."
        PRD §3.8: "Its `required_sample_size` is the larger of 2 units and two percent of the order's `built_quantity` rounded **up** to a whole unit, and it is likewise frozen — later releases on the order do not enlarge it."

        Design: Difficulty/boundary_precision_check/audit_failure_rate_exactly_at_quarter_threshold
        """
        scenario = build_released_order_plant()
        build_and_release_units(scenario, 4)
        assert read_family(scenario.family_id)[
            "family_emission_limit_g_per_kwh"
        ] == pytest.approx(8.00, abs=0.005)
        audit = schedule_line_audit(scenario.build_order_id, audit_week="2026-09-21")
        assert audit["required_sample_size"] == 2

        # 5.60 is well under the family limit, so only the rate can breach.
        recorded = record_line_audit(
            audit["id"],
            units_tested=4,
            units_failed=2,
            max_measured_emission_g_per_kwh=5.60,
        )

        assert recorded["failure_rate"] == pytest.approx(0.5000, abs=0.00005)
        assert recorded["status"] == "FAILED"
        assert recorded["failure_reason"] == "FAILURE_RATE_EXCEEDED"

        family = read_family(scenario.family_id)
        assert family["status"] == "AUDIT_HOLD"
        assert family["cumulative_audit_failures"] == 1


class TestAllocatablePoolFloor:
    """One released unit is the smallest pool the waterfall can run on."""

    def test_an_empty_released_pool_refuses_the_allocation_run(self, canonical_clock):
        """PRD §3.8: "The allocation pool is exactly the order's `built_quantity` — units whose `build_state` is `RELEASED`."
        PRD §3.8: "Units still `STAGED`, `ASSEMBLED` or `HOT_TESTED`, units `CANCELLED`, and units belonging to any other order are all excluded."
        PRD §3.8: "Running allocation on an order whose released pool is empty is refused with `ERR_NO_ALLOCATABLE_UNITS`."

        Design: Difficulty/boundary_precision_check/allocatable_pool_boundary_zero_versus_one_released_unit
        """
        scenario = build_released_order_plant()
        stage_engine_unit(scenario, "SN-0001")
        order = read_build_order(scenario.build_order_id)
        assert order["built_quantity"] == 0
        assert order["staged_quantity"] == 1

        response = api_client.run_build_order_allocations(
            scenario.build_order_id,
            run_allocations_payload(order["version"]),
            PRODUCTION_PLANNER,
        )

        validate_error(response, ApiErrorId.ERR_NO_ALLOCATABLE_UNITS.value)

        untouched = read_build_order(scenario.build_order_id)
        assert untouched["allocation_status"] == "UNALLOCATED"
        assert untouched["allocation_run_at"] is None
        assert untouched["unallocated_units"] == 0

    def test_a_single_released_unit_is_allocated_in_full_to_the_dealer_channel(
        self, canonical_clock
    ):
        """PRD §3.8: "Both raw shares are rounded **down** to whole units."
        PRD §3.8: "When it is 1, that single unit goes to whichever bucket had the larger fractional part, and when the two fractional parts are equal the unit goes to the **dealer** bucket."
        PRD §3.8: "The results are written as `allocated_dealer_units`, `allocated_mass_retail_units` and `unallocated_units`, `allocation_status` becomes `ALLOCATED`, `allocation_run_at` is stamped from the clock, and the order's `version` increments by 1."

        Design: Difficulty/boundary_precision_check/allocatable_pool_boundary_zero_versus_one_released_unit
        """
        scenario = build_released_order_plant()
        build_and_release_unit(scenario, "SN-0001")
        version_before = build_order_version(scenario.build_order_id)

        response = api_client.run_build_order_allocations(
            scenario.build_order_id,
            run_allocations_payload(version_before),
            PRODUCTION_PLANNER,
        )
        allocated = response.json()["data"]

        # 1 * 0.55 floors to 0 and 1 * 0.45 floors to 0; the remainder unit
        # follows the larger fractional part.
        assert allocated["allocated_dealer_units"] == 1
        assert allocated["allocated_mass_retail_units"] == 0
        assert allocated["unallocated_units"] == 0
        assert allocated["allocation_status"] == "ALLOCATED"
        assert allocated["allocation_run_at"].startswith("2026-08-03T08:00:00")
        assert allocated["version"] == version_before + 1


class TestTorqueBandEdges:
    """Both ends of the derived torque band are inside the band."""

    def test_readings_sitting_exactly_on_both_edges_count_no_fastener_out_of_spec(
        self, canonical_clock
    ):
        """PRD §3.7: "The tolerance band is derived from the platform: the lower bound is `torque_spec_nm` multiplied by one minus `torque_tolerance_pct`, rounded half up to 2 decimal places, and the upper bound is `torque_spec_nm` multiplied by one plus `torque_tolerance_pct`, rounded half up to 2 decimal places."
        PRD §3.7: "The band is **inclusive** at both ends."
        PRD §3.7: "A platform specified at 22.0 Nm with a tolerance of 0.05 therefore accepts everything from 20.90 through 23.10 inclusive."

        Design: Difficulty/boundary_precision_check/torque_reading_inclusive_band_edges
        """
        scenario = build_released_order_plant()
        staged = stage_engine_unit(scenario, "SN-0001")

        recorded = record_torque(staged["id"], EDGE_READINGS)

        assert recorded["out_of_spec_fastener_count"] == 0
        assert recorded["build_state"] == "ASSEMBLED"
        assert recorded["conformance_state"] == "PENDING"

    def test_one_hundredth_outside_each_edge_counts_two_fasteners_out_of_spec(
        self, canonical_clock
    ):
        """PRD §3.7: "`out_of_spec_fastener_count` is the number of readings whose `torque_nm` is strictly below the lower bound or strictly above the upper bound."
        PRD §3.7: "The unit's `build_state` advances `STAGED → ASSEMBLED` regardless of the count, and its `conformance_state` becomes `NONCONFORMING` when `out_of_spec_fastener_count` is greater than zero, or is left at `PENDING` when every fastener was in band."
        PRD §3.7: "Progress counters are always the plain counts they claim to be: `staged_quantity` is the number of the order's units whose `build_state` is `STAGED`, `ASSEMBLED` or `HOT_TESTED`, `built_quantity` is the number whose `build_state` is `RELEASED`, and a `CANCELLED` unit counts toward neither."

        Design: Difficulty/boundary_precision_check/torque_reading_inclusive_band_edges
        """
        scenario = build_released_order_plant()
        on_the_edge = stage_engine_unit(scenario, "SN-0001")
        just_outside = stage_engine_unit(scenario, "SN-0002")

        record_torque(on_the_edge["id"], EDGE_READINGS)
        recorded = record_torque(just_outside["id"], JUST_OUTSIDE_READINGS)

        assert recorded["out_of_spec_fastener_count"] == 2
        assert recorded["build_state"] == "ASSEMBLED"
        assert recorded["conformance_state"] == "NONCONFORMING"
        assert read_engine_unit(on_the_edge["id"])["out_of_spec_fastener_count"] == 0

        order = read_build_order(scenario.build_order_id)
        assert order["staged_quantity"] == 2
        assert order["built_quantity"] == 0
