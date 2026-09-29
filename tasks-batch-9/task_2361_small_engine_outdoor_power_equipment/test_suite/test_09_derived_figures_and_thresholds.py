"""Derived plant figures: hot-test thresholds, certification arithmetic, carry
cost, the channel waterfall, parts fill rate, supersession chains, platform
posture and the counters an audit samples from.
"""

import pytest

from test_helpers import (
    EXPECTED_DEVIATION_HOT_TEST_THRESHOLD,
    EXPECTED_MAJOR_ACCEPTANCE_NUMBER_40,
    EXPECTED_NORMAL_SAMPLE_SIZE_800,
    EXPECTED_STANDARD_HOT_TEST_THRESHOLD,
    ApiErrorId,
    assert_build_order_unit_conservation,
    assert_decimal_places,
    assert_lot_piece_conservation,
    assert_whole_cents,
    build_and_release_unit,
    build_assembly_line,
    build_certification_family,
    build_engine_platform,
    build_product_model,
    build_safety_certification,
    build_service_part,
    cancel_engine_unit,
    certify_family,
    complete_durability_run,
    deviation_accept_lot,
    hot_test_unit,
    inspect_component_lot,
    is_iso8601_timestamp,
    plan_build_order,
    raise_parts_request,
    read_family,
    read_lot,
    read_platform,
    read_service_part,
    read_supplier_scorecard,
    receive_component_lot,
    record_torque,
    release_build_order,
    release_engine_unit,
    release_product_model,
    run_allocations,
    schedule_durability_run,
    schedule_line_audit,
    stage_engine_unit,
    submit_family,
    supersede_service_part,
    supersede_service_part_payload,
    validate_error,
    validate_paginated,
)


class TestHotTestThresholdAndWindow:
    """The two inclusive hot-test gates and the certified-emission allowance."""

    def test_hot_test_window_and_emission_threshold_decide_conformance(
        self, released_order_plant
    ):
        """PRD §3.7: "The unit's `hot_test_emission_threshold` is derived from the certified emission of the family owning its platform, multiplied by a factor and rounded half up to 2 decimal places."
        PRD §3.7: "For an ordinary unit the factor is 1.10, allowing a ten percent production allowance above the certified value."
        PRD §3.7: "The unit passes when both of two inclusive comparisons hold: `measured_rpm` lies at or above the platform's `hot_test_min_rpm` and at or below its `hot_test_max_rpm`, and `measured_emission_g_per_kwh` is at most `hot_test_emission_threshold`."
        PRD §3.7: "The `build_state` advances `ASSEMBLED → HOT_TESTED` either way, and `conformance_state` becomes `CONFORMING` when both comparisons hold and `NONCONFORMING` when either fails."
        PRD §3.7: "Progress counters are always the plain counts they claim to be: `staged_quantity` is the number of the order's units whose `build_state` is `STAGED`, `ASSEMBLED` or `HOT_TESTED`, `built_quantity` is the number whose `build_state` is `RELEASED`, and a `CANCELLED` unit counts toward neither."

        Design: Corner/calculations/hot_test_rpm_window_and_emission_threshold_correct_result
        """
        scenario = released_order_plant

        inside = stage_engine_unit(scenario, "SN-0001")
        record_torque(inside["id"])
        inside = hot_test_unit(
            inside["id"], measured_rpm=3400, measured_emission_g_per_kwh=5.60
        )

        over_speed = stage_engine_unit(scenario, "SN-0002")
        record_torque(over_speed["id"])
        over_speed = hot_test_unit(
            over_speed["id"], measured_rpm=3700, measured_emission_g_per_kwh=5.60
        )

        on_both_edges = stage_engine_unit(scenario, "SN-0003")
        record_torque(on_both_edges["id"])
        on_both_edges = hot_test_unit(
            on_both_edges["id"], measured_rpm=3200, measured_emission_g_per_kwh=5.63
        )

        # 5.12 certified * 1.10, never 8.00 limit * 1.10.
        for unit in (inside, over_speed, on_both_edges):
            assert unit["build_state"] == "HOT_TESTED"
            assert_decimal_places(
                unit["hot_test_emission_threshold"], 2, "hot_test_emission_threshold"
            )
            assert unit["hot_test_emission_threshold"] == pytest.approx(
                EXPECTED_STANDARD_HOT_TEST_THRESHOLD, abs=0.01
            )

        assert inside["conformance_state"] == "CONFORMING"
        assert over_speed["conformance_state"] == "NONCONFORMING"
        assert on_both_edges["conformance_state"] == "CONFORMING"

        order = scenario.refresh_build_order()
        assert order["built_quantity"] == 0
        assert order["staged_quantity"] == 3

    def test_nonconforming_unit_is_refused_release_while_its_sibling_passes(
        self, api, quality_engineer_headers, released_order_plant
    ):
        """PRD §3.7: "Releasing a unit to finished goods requires `build_state` `HOT_TESTED`, else `ERR_UNIT_STATE_INVALID`; `conformance_state` `CONFORMING`, else `ERR_UNIT_NONCONFORMING`; and a parent order whose status is `RELEASED` or `IN_PRODUCTION`."
        PRD §3.7: "Progress counters are always the plain counts they claim to be: `staged_quantity` is the number of the order's units whose `build_state` is `STAGED`, `ASSEMBLED` or `HOT_TESTED`, `built_quantity` is the number whose `build_state` is `RELEASED`, and a `CANCELLED` unit counts toward neither."

        Design: Corner/calculations/hot_test_rpm_window_and_emission_threshold_correct_result
        """
        scenario = released_order_plant

        conforming = stage_engine_unit(scenario, "SN-0001")
        record_torque(conforming["id"])
        hot_test_unit(
            conforming["id"], measured_rpm=3400, measured_emission_g_per_kwh=5.60
        )

        nonconforming = stage_engine_unit(scenario, "SN-0002")
        record_torque(nonconforming["id"])
        hot_test_unit(
            nonconforming["id"], measured_rpm=3700, measured_emission_g_per_kwh=5.60
        )

        validate_error(
            api.release_engine_unit(nonconforming["id"], quality_engineer_headers),
            ApiErrorId.ERR_UNIT_NONCONFORMING,
        )

        released = release_engine_unit(conforming["id"])
        assert released["build_state"] == "RELEASED"

        order = scenario.refresh_build_order()
        assert order["built_quantity"] == 1
        assert order["staged_quantity"] == 1
        assert_build_order_unit_conservation(order)

    def test_deviation_sourced_unit_is_judged_at_the_certified_emission_exactly(
        self, released_order_plant
    ):
        """PRD §3.7: "For a `deviation_sourced` unit the factor is 1.00, so the allowance disappears entirely and the engine must meet the certified emission exactly — this is the price of accepting a deviated component."
        PRD §3.7: "Its `deviation_sourced` flag is set true when *either* consumed lot carries `deviation_flag` true, and false only when neither does."
        PRD §3.4: "The disposition forks on the frozen acceptance number: when `defects_found` is at most `acceptance_number` the lot moves `RECEIVED → ACCEPTED`, and when it is greater the lot moves `RECEIVED → REJECTED`."
        PRD §3.4: "On success the lot moves to `DEVIATION_ACCEPTED`, `deviation_flag` becomes true, `deviation_approved_by_user_id` records the approver, and the released quantity is recomputed: `accepted_qty` becomes `lot_quantity` minus `defects_found`, with `remaining_qty` set equal to it."
        PRD §3.4: "The pooled rate is the sum of `defects_found` across that population, divided by the sum of `sample_size` across the same population, multiplied by one million, rounded half up to a whole number, and stored as `rolling_defect_ppm`."
        PRD §3.4: "Otherwise: if the recomputed pooled rate is **greater than** 100,000 parts per million, the supplier becomes `SUSPENDED` and its `incoming_inspection_level` becomes `TIGHTENED`; else if the pooled rate is **greater than** 25,000 parts per million, the supplier becomes `PROBATION` and its level becomes `TIGHTENED`; else the supplier becomes `APPROVED` and its level is chosen from the accepted-lot streak — `SKIP_LOT` when `consecutive_accepted_lots` is at least 5, `REDUCED` when it is at least 3, and `NORMAL` otherwise."

        Design: Corner/calculations/deviation_sourced_hot_test_uses_the_tightened_multiplier
        """
        scenario = released_order_plant

        # The clean sibling is taken all the way through its hot test first, so
        # the later supplier downgrade cannot touch it.
        clean = stage_engine_unit(scenario, "SN-0001")
        record_torque(clean["id"])
        clean = hot_test_unit(
            clean["id"], measured_rpm=3400, measured_emission_g_per_kwh=5.60
        )
        assert clean["deviation_sourced"] is False
        assert clean["hot_test_emission_threshold"] == pytest.approx(
            EXPECTED_STANDARD_HOT_TEST_THRESHOLD, abs=0.01
        )
        assert clean["conformance_state"] == "CONFORMING"

        carburetor_supplier_id = scenario.suppliers["carburetor"]["id"]
        deviated = receive_component_lot(
            carburetor_supplier_id, lot_code="CB-DEV", lot_quantity=800
        )
        assert deviated["sample_size"] == EXPECTED_NORMAL_SAMPLE_SIZE_800
        assert deviated["acceptance_number"] == EXPECTED_MAJOR_ACCEPTANCE_NUMBER_40

        deviated = inspect_component_lot(deviated["id"], defects_found=5)
        assert deviated["status"] == "REJECTED"

        supplier = read_supplier_scorecard(carburetor_supplier_id)
        assert supplier["rolling_defect_ppm"] == 62_500
        assert supplier["approval_status"] == "PROBATION"
        assert supplier["incoming_inspection_level"] == "TIGHTENED"

        deviated = deviation_accept_lot(deviated["id"])
        assert deviated["status"] == "DEVIATION_ACCEPTED"
        assert deviated["deviation_flag"] is True
        assert deviated["accepted_qty"] == 795
        assert deviated["remaining_qty"] == 795
        assert_lot_piece_conservation(deviated)

        tainted = stage_engine_unit(
            scenario, "SN-0005", carburetor_lot_id=deviated["id"]
        )
        assert tainted["deviation_sourced"] is True
        record_torque(tainted["id"])
        tainted = hot_test_unit(
            tainted["id"], measured_rpm=3400, measured_emission_g_per_kwh=5.60
        )

        assert tainted["hot_test_emission_threshold"] == pytest.approx(
            EXPECTED_DEVIATION_HOT_TEST_THRESHOLD, abs=0.01
        )
        assert tainted["build_state"] == "HOT_TESTED"
        # The identical 5.60 reading that the clean sibling passed.
        assert tainted["conformance_state"] == "NONCONFORMING"


class TestCertificationArithmeticGates:
    """The compliance margin is an inclusive floor on rounded intermediates."""

    def test_compliance_margin_of_exactly_five_percent_certifies(self, canonical_clock):
        """PRD §3.2: "Under `MULTIPLICATIVE`, the deterioration factor is 1 plus the quantity (the raw factor minus 1) multiplied by the scaling factor."
        PRD §3.2: "Under `MULTIPLICATIVE`, the certified emission is the family's `declared_baseline_emission_g_per_kwh` multiplied by the rounded deterioration factor."
        PRD §3.2: "The compliance margin is the family's `family_emission_limit_g_per_kwh` minus the rounded certified emission, divided by that same `family_emission_limit_g_per_kwh`, multiplied by 100, and rounded half up to 2 decimal places."
        PRD §3.2: "Four conditions must hold, and they are checked in the ladder order of §2.8: the family must be in `SUBMITTED`; the certifying operator must differ from `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; the family's `certified_emission_g_per_kwh` must be at most its `family_emission_limit_g_per_kwh`, else `ERR_CERTIFIED_EMISSION_EXCEEDS_LIMIT`; and the family's `compliance_margin_pct` must be at least 5.00 percent, else `ERR_COMPLIANCE_MARGIN_TOO_LOW`."
        PRD §3.2: "On success the family moves `SUBMITTED → CERTIFIED`, `certified_by_user_id` records the certifying operator, `certified_at` is stamped from the clock, and every platform of the family has its posture recomputed to `OPEN`."

        Design: Corner/calculations/compliance_margin_gate_at_exactly_five_percent
        """
        family = build_certification_family(family_code="2027-EPA-PASS")
        platform = build_engine_platform(family["id"], platform_code="208PASS")
        run = schedule_durability_run(family["id"], platform["id"])
        complete_durability_run(run["id"], final_emission_g_per_kwh=9.50)
        submit_family(family["id"])

        certified = certify_family(family["id"])

        assert_decimal_places(
            certified["deterioration_factor"], 4, "deterioration_factor"
        )
        assert certified["deterioration_factor"] == pytest.approx(1.9000, abs=0.0001)
        assert certified["certified_emission_g_per_kwh"] == pytest.approx(7.60, abs=0.01)
        assert certified["compliance_margin_pct"] == pytest.approx(5.00, abs=0.01)
        assert certified["status"] == "CERTIFIED"
        assert read_platform(platform["id"])["certification_posture"] == "OPEN"

    def test_compliance_margin_below_five_percent_is_refused_and_changes_nothing(
        self, api, compliance_officer_headers, canonical_clock
    ):
        """PRD §3.2: "Four conditions must hold, and they are checked in the ladder order of §2.8: the family must be in `SUBMITTED`; the certifying operator must differ from `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; the family's `certified_emission_g_per_kwh` must be at most its `family_emission_limit_g_per_kwh`, else `ERR_CERTIFIED_EMISSION_EXCEEDS_LIMIT`; and the family's `compliance_margin_pct` must be at least 5.00 percent, else `ERR_COMPLIANCE_MARGIN_TOO_LOW`."
        PRD §3.2: "The three results are written to the family as `deterioration_factor`, `certified_emission_g_per_kwh` and `compliance_margin_pct`, and the family advances to `DURABILITY_COMPLETE`."
        PRD §2.7: "a family in `DURABILITY_TESTING`, `DURABILITY_COMPLETE`, `SUBMITTED` or `AUDIT_HOLD` projects posture `RESTRICTED`"

        Design: Corner/calculations/compliance_margin_gate_at_exactly_five_percent
        """
        family = build_certification_family(family_code="2027-EPA-FAIL")
        platform = build_engine_platform(family["id"], platform_code="208FAIL")
        run = schedule_durability_run(family["id"], platform["id"])
        complete_durability_run(run["id"], final_emission_g_per_kwh=9.52)
        submit_family(family["id"])

        validate_error(
            api.certify_certification_family(family["id"], compliance_officer_headers),
            ApiErrorId.ERR_COMPLIANCE_MARGIN_TOO_LOW,
        )

        refused = read_family(family["id"])
        assert refused["deterioration_factor"] == pytest.approx(1.9040, abs=0.0001)
        # 7.616 rounded half up at 2 decimal places.
        assert refused["certified_emission_g_per_kwh"] == pytest.approx(7.62, abs=0.01)
        assert refused["compliance_margin_pct"] == pytest.approx(4.75, abs=0.01)
        assert refused["status"] == "SUBMITTED"
        assert read_platform(platform["id"])["certification_posture"] == "RESTRICTED"


class TestBuildOrderCarryCost:
    """Carry rate tiers, whole-week counting and half-up rounding to cents."""

    def test_carry_tier_ceiling_is_inclusive_at_twenty_million_cents(
        self, family_with_platform
    ):
        """PRD §3.6: "`build_value_cents` is `planned_quantity` multiplied by the model's `standard_cost_cents`."
        PRD §3.6: "The weekly `carry_rate` is then selected **from `build_value_cents` alone**: 0.0040 when the build value is below 5,000,000 cents, 0.0030 when it is below 20,000,000 cents, and 0.0020 otherwise — so the tier ceilings are exclusive at the bottom of the next tier and a build value of exactly 20,000,000 cents lands on the 0.0020 rate."
        PRD §3.6: "`carry_weeks` is 0 for an `IN_SEASON` order; for a `PRE_SEASON` order it is the number of whole weeks from `production_week` to the product line's season start, that is, the day count between the two dates divided by 7 and rounded **down**."
        PRD §3.6: "`carry_cost_cents` is `build_value_cents` multiplied by `carry_rate` multiplied by `carry_weeks`, rounded half up to whole cents."
        PRD §3.6: "`total_committed_cents` is `build_value_cents` plus `carry_cost_cents`."
        PRD §3.6: "That last sum is what the plant commits, but it never feeds back into tier selection: the carry rate is chosen from the build value and only from the build value, however large the resulting total becomes."
        PRD §3.6: "The four season starts are fixed dates: walk-behind mowers open on 2027-03-01, riding mowers on 2027-03-15, snow equipment much earlier on 2026-11-02, and generators on 2027-05-03."

        Design: Corner/calculations/carry_tier_ceiling_is_inclusive_at_twenty_million_cents
        """
        scenario = family_with_platform
        model = build_product_model(
            scenario.platform_id,
            model_code="WM-20000",
            standard_cost_cents=20_000,
            dealer_cap_units=1000,
            mass_retail_cap_units=1000,
        )
        build_safety_certification(model["id"])
        release_product_model(model["id"])

        line_a = build_assembly_line(
            line_code="L-A",
            supported_product_lines=["WALK_MOWER"],
            weekly_capacity_units=500,
        )
        line_b = build_assembly_line(
            line_code="L-B",
            supported_product_lines=["WALK_MOWER"],
            weekly_capacity_units=500,
        )

        # 2026-09-14 to the walk-behind mower season start 2027-03-01 is 168
        # days, that is 24 whole weeks.
        on_the_ceiling = plan_build_order(
            model["id"],
            line_a["id"],
            season="PRE_SEASON",
            production_week="2026-09-14",
            week_span=2,
            planned_quantity=1000,
        )
        one_step_below = plan_build_order(
            model["id"],
            line_b["id"],
            season="PRE_SEASON",
            production_week="2026-09-14",
            week_span=2,
            planned_quantity=999,
        )

        assert on_the_ceiling["build_value_cents"] == 20_000_000
        assert on_the_ceiling["carry_rate"] == pytest.approx(0.0020, abs=0.000001)
        assert on_the_ceiling["carry_weeks"] == 24
        assert on_the_ceiling["carry_cost_cents"] == 960_000
        assert on_the_ceiling["total_committed_cents"] == 20_960_000

        assert one_step_below["build_value_cents"] == 19_980_000
        assert one_step_below["carry_rate"] == pytest.approx(0.0030, abs=0.000001)
        assert one_step_below["carry_weeks"] == 24
        assert one_step_below["carry_cost_cents"] == 1_438_560
        assert one_step_below["total_committed_cents"] == 21_418_560

        for order in (on_the_ceiling, one_step_below):
            assert_whole_cents(order["build_value_cents"], "build_value_cents")
            assert_whole_cents(order["carry_cost_cents"], "carry_cost_cents")
            assert_whole_cents(order["total_committed_cents"], "total_committed_cents")

        # One unit fewer commits 458,560 cents more; the ladder never re-reads
        # the committed total.
        assert (
            one_step_below["total_committed_cents"]
            - on_the_ceiling["total_committed_cents"]
            == 458_560
        )

    def test_carry_cost_rounds_half_up_and_in_season_carries_zero_weeks(
        self, family_with_platform
    ):
        """PRD §3.6: "`carry_cost_cents` is `build_value_cents` multiplied by `carry_rate` multiplied by `carry_weeks`, rounded half up to whole cents."
        PRD §3.6: "`carry_weeks` is 0 for an `IN_SEASON` order; for a `PRE_SEASON` order it is the number of whole weeks from `production_week` to the product line's season start, that is, the day count between the two dates divided by 7 and rounded **down**."
        PRD §3.6: "The four season starts are fixed dates: walk-behind mowers open on 2027-03-01, riding mowers on 2027-03-15, snow equipment much earlier on 2026-11-02, and generators on 2027-05-03."
        PRD §3.6: "`total_committed_cents` is `build_value_cents` plus `carry_cost_cents`."
        PRD §2.6: "`carry_cost_cents`, `build_value_cents` and `total_committed_cents` are integers; the weekly `carry_rate` is carried at 4 decimal places."

        Design: Corner/calculations/carry_cost_rounds_half_up_and_in_season_carries_zero_weeks
        """
        scenario = family_with_platform
        model = build_product_model(
            scenario.platform_id,
            model_code="ST-24-DLR",
            product_line="SNOW_THROWER",
            channel="DEALER",
            blade_brake_type="ENGINE_KILL",
            operator_presence_type="TWO_HAND",
            warranty_months=36,
            standard_cost_cents=20_125,
            msrp_cents=99_900,
            dealer_share_pct=1.00,
            dealer_cap_units=500,
            mass_retail_cap_units=0,
        )
        build_safety_certification(
            model["id"], standard_code="ANSI_B71_3", blade_stop_time_ms=2400
        )
        release_product_model(model["id"])

        line = build_assembly_line(
            line_code="L-SNOW",
            supported_product_lines=["SNOW_THROWER"],
            weekly_capacity_units=500,
        )

        # 2026-10-26 to the snow equipment season start 2026-11-02 is 7 days.
        pre_season = plan_build_order(
            model["id"],
            line["id"],
            season="PRE_SEASON",
            production_week="2026-10-26",
            week_span=1,
            planned_quantity=1,
        )
        in_season = plan_build_order(
            model["id"],
            line["id"],
            season="IN_SEASON",
            production_week="2026-11-02",
            week_span=1,
            planned_quantity=2,
        )

        assert pre_season["build_value_cents"] == 20_125
        assert pre_season["carry_rate"] == pytest.approx(0.0040, abs=0.000001)
        assert pre_season["carry_weeks"] == 1
        # 20,125 * 0.0040 * 1 is 80.5 raw cents, which rounds half up to 81.
        assert pre_season["carry_cost_cents"] == 81
        assert pre_season["total_committed_cents"] == 20_206

        assert in_season["season"] == "IN_SEASON"
        assert in_season["carry_weeks"] == 0
        assert in_season["carry_cost_cents"] == 0
        assert in_season["build_value_cents"] == 40_250
        assert in_season["total_committed_cents"] == 40_250


class TestChannelAllocationWaterfall:
    """The two channel ceilings behave asymmetrically."""

    def test_mass_cap_spills_to_dealer_and_dealer_cap_is_held_back(
        self, production_ready_plant
    ):
        """PRD §3.8: "The allocation pool is exactly the order's `built_quantity` — units whose `build_state` is `RELEASED`."
        PRD §3.8: "The raw dealer share is the pool multiplied by the model's `dealer_share_pct`, and the raw mass-retail share is the pool multiplied by one minus `dealer_share_pct`."
        PRD §3.8: "Both raw shares are rounded **down** to whole units."
        PRD §3.8: "When it is 1, that single unit goes to whichever bucket had the larger fractional part, and when the two fractional parts are equal the unit goes to the **dealer** bucket."
        PRD §3.8: "If the mass-retail figure exceeds the model's `mass_retail_cap_units`, the excess above that cap is moved over to the dealer figure and the mass-retail figure is set to the cap."
        PRD §3.8: "If the dealer figure — now possibly inflated by the spill from step two — exceeds the model's `dealer_cap_units`, the excess above that cap becomes `unallocated_units` and the dealer figure is set to the cap."
        PRD §3.8: "The results are written as `allocated_dealer_units`, `allocated_mass_retail_units` and `unallocated_units`, `allocation_status` becomes `ALLOCATED`, `allocation_run_at` is stamped from the clock, and the order's `version` increments by 1."
        PRD §2.11: "On a build order, the released population is conserved across channels: `built_quantity` always equals `allocated_dealer_units` plus `allocated_mass_retail_units` plus `unallocated_units`."
        PRD §3.7: "When the release brings `built_quantity` up to the order's `planned_quantity`, the order transitions `IN_PRODUCTION → COMPLETED` in the same request; a `COMPLETED` order accepts no further units, though allocation runs remain permitted on it."

        Design: Corner/calculations/waterfall_mass_cap_spills_to_dealer_and_dealer_cap_is_held_back
        """
        scenario = production_ready_plant
        capped_model = build_product_model(
            scenario.platform_id,
            model_code="WM-21-CAP",
            dealer_cap_units=2,
            mass_retail_cap_units=0,
        )
        build_safety_certification(capped_model["id"])
        scenario.model = release_product_model(capped_model["id"])

        planned = plan_build_order(
            scenario.model_id,
            scenario.line_id,
            season="PRE_SEASON",
            production_week="2026-09-14",
            week_span=1,
            planned_quantity=3,
        )
        scenario.build_order = release_build_order(planned["id"])

        for serial in ("SN-0021", "SN-0022", "SN-0023"):
            build_and_release_unit(scenario, serial)

        before = scenario.refresh_build_order()
        assert before["built_quantity"] == 3
        assert before["status"] == "COMPLETED"

        allocated = run_allocations(scenario.build_order_id, before["version"])

        # Raw 1.65 / 1.35 floors to 1 / 1; the remainder goes to the larger
        # fraction (dealer), giving 2 / 1. Mass retail's unit then spills into
        # dealer, and dealer's own excess above 2 is held back.
        assert allocated["allocated_dealer_units"] == 2
        assert allocated["allocated_mass_retail_units"] == 0
        assert allocated["unallocated_units"] == 1
        assert allocated["allocation_status"] == "ALLOCATED"
        assert allocated["version"] == before["version"] + 1
        assert is_iso8601_timestamp(allocated["allocation_run_at"])
        assert allocated["allocation_run_at"].startswith("2026-08-03T08:00:00")
        assert_build_order_unit_conservation(allocated)


class TestServicePartFillRate:
    """Stock is consumed per request, and the promise date follows the channel."""

    def test_fill_rate_aggregates_served_over_total_with_no_partial_fills(
        self, family_with_platform
    ):
        """PRD §3.9: "The request is minted in `BACKORDERED` and settles within the very same call when stock allows: if the part's `on_hand_qty` is at least `requested_quantity`, the request becomes `FILLED`, its `shipped_from_part_id` is set to the part it was requested from, and the part's `on_hand_qty` is reduced by `requested_quantity`."
        PRD §3.9: "If stock does not cover the request it stays `BACKORDERED` — there are no partial fills."
        PRD §3.9: "A request that is `FILLED` or `SUBSTITUTED` gets `promised_ship_date` equal to the clock date plus the lead time its channel earns — `dealer_lead_time_days` for a `DEALER` request and `mass_retail_lead_time_days` for a `MASS_RETAIL` request, read from the part the pieces actually ship from."
        PRD §3.9: "A request left `BACKORDERED` gets `promised_ship_date` equal to the clock date plus 21 days."
        PRD §3.9: "The served count is `filled_request_count` plus `substituted_request_count`; the total is that served count plus `backordered_request_count`."
        PRD §3.9: "Otherwise it is the served count divided by the total, multiplied by 100, rounded half up to 2 decimal places."
        PRD §2.6: "`fill_rate_pct` on a service part carries 2 decimal places — two served requests out of three total give 66.67."

        Design: Corner/calculations/fill_rate_aggregates_served_over_total_with_no_partial_fills
        """
        scenario = family_with_platform
        part = build_service_part(
            scenario.platform_id,
            part_number="PN-CARB-KIT-2",
            on_hand_qty=2,
            dealer_lead_time_days=2,
            mass_retail_lead_time_days=5,
        )

        filled_dealer = raise_parts_request(
            part["id"], requested_quantity=1, channel="DEALER"
        )
        assert filled_dealer["status"] == "FILLED"
        assert filled_dealer["promised_ship_date"] == "2026-08-05"
        assert filled_dealer["shipped_from_part_id"] == part["id"]

        # Only 1 piece is left, so a 2-piece request is not partially filled.
        backordered = raise_parts_request(
            part["id"], requested_quantity=2, channel="DEALER"
        )
        assert backordered["status"] == "BACKORDERED"
        assert backordered["promised_ship_date"] == "2026-08-24"
        assert backordered.get("shipped_from_part_id") is None

        # The waiting request does not block the one behind it.
        filled_mass_retail = raise_parts_request(
            part["id"], requested_quantity=1, channel="MASS_RETAIL"
        )
        assert filled_mass_retail["status"] == "FILLED"
        assert filled_mass_retail["promised_ship_date"] == "2026-08-08"
        assert filled_mass_retail["shipped_from_part_id"] == part["id"]

        refreshed = read_service_part(part["id"])
        assert refreshed["on_hand_qty"] == 0
        assert refreshed["filled_request_count"] == 2
        assert refreshed["substituted_request_count"] == 0
        assert refreshed["backordered_request_count"] == 1
        assert_decimal_places(refreshed["fill_rate_pct"], 2, "fill_rate_pct")
        assert refreshed["fill_rate_pct"] == pytest.approx(66.67, abs=0.01)


class TestSupersessionChain:
    """Supersession is a strict forward DAG built onto ACTIVE successors."""

    def test_self_reference_is_refused_and_the_forward_chain_walks_five_hops(
        self, api, plant_admin_headers, family_with_platform
    ):
        """PRD §3.9: "And the resulting chain must be well-formed: the successor may not be the part itself, and walking forward from the successor along `superseded_by_part_id` must never arrive back at the part being superseded, and the resulting chain — one link plus the length of the successor's existing chain — must be at most 5 links deep."
        PRD §3.9: "Any of those three failures is refused with `ERR_SUPERSESSION_CYCLE`."
        PRD §3.9: "The part being superseded must be `ACTIVE` and the named successor must also be `ACTIVE`, else `ERR_PART_STATE_INVALID`."
        PRD §3.9: "The part moves `ACTIVE → SUPERSEDED` and its `superseded_by_part_id` is set to the successor."
        PRD §3.9: "When the total is zero, `fill_rate_pct` is empty."
        PRD §2.8: "The rules are evaluated in a fixed order and **the first violated rule decides the response** — later rules are never reported."
        PRD §3.9: "Service parts are readable individually and as a list, filterable by `engine_platform_id`, by `superseded_by_part_id` to trace supersession pointers, by `status` and by `category`."

        Design: Corner/calculations/supersession_chain_walks_forward_and_rejects_self_reference
        """
        scenario = family_with_platform
        parts = [
            build_service_part(
                scenario.platform_id, part_number=f"PN-P{index}", on_hand_qty=0
            )
            for index in range(1, 7)
        ]

        validate_error(
            api.supersede_service_part(
                parts[0]["id"],
                supersede_service_part_payload(parts[0]["id"]),
                plant_admin_headers,
            ),
            ApiErrorId.ERR_SUPERSESSION_CYCLE,
        )
        head = read_service_part(parts[0]["id"])
        assert head["status"] == "ACTIVE"
        assert head.get("superseded_by_part_id") is None

        for predecessor, successor in zip(parts, parts[1:]):
            moved = supersede_service_part(predecessor["id"], successor["id"])
            assert moved["status"] == "SUPERSEDED"
            assert moved["superseded_by_part_id"] == successor["id"]
            # No request ever existed against these parts.
            assert moved.get("fill_rate_pct") is None

        tail = read_service_part(parts[5]["id"])
        assert tail["status"] == "ACTIVE"
        assert tail.get("superseded_by_part_id") is None

        # The loop-closing attempt is refused on the state axis, which the
        # ladder reaches before the chain check.
        validate_error(
            api.supersede_service_part(
                parts[5]["id"],
                supersede_service_part_payload(parts[0]["id"]),
                plant_admin_headers,
            ),
            ApiErrorId.ERR_PART_STATE_INVALID,
        )
        tail = read_service_part(parts[5]["id"])
        assert tail["status"] == "ACTIVE"
        assert tail.get("superseded_by_part_id") is None

        # The pointer is a single hop, never a transitive closure.
        rows, meta = validate_paginated(
            api.list_service_parts(
                plant_admin_headers,
                {"superseded_by_part_id": parts[5]["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [parts[4]["id"]]


class TestPlatformPostureProjection:
    """Posture is a total projection of the owning family's status."""

    def test_posture_follows_every_family_status(self, family_with_platform):
        """PRD §2.7: "An `EnginePlatform` does not hold an independent regulatory state of its own: its `certification_posture` is a pure projection of the owning family's `status`, recomputed inside the very same request that changes that status."
        PRD §2.7: "a family in `DRAFT` projects posture `PENDING`"
        PRD §2.7: "a family in `DURABILITY_TESTING`, `DURABILITY_COMPLETE`, `SUBMITTED` or `AUDIT_HOLD` projects posture `RESTRICTED`"
        PRD §2.7: "a family in `CERTIFIED` projects posture `OPEN`"
        PRD §3.2: "Three things then happen to the surrounding graph: the family advances to `DURABILITY_TESTING` (from `DRAFT` or from `AUDIT_HOLD`; a family already in `DURABILITY_TESTING` stays there and simply carries an additional scheduled run), the family's `version` increments by 1, and every platform of the family has its `certification_posture` recomputed, landing on `RESTRICTED`."
        PRD §3.2: "The three results are written to the family as `deterioration_factor`, `certified_emission_g_per_kwh` and `compliance_margin_pct`, and the family advances to `DURABILITY_COMPLETE`."
        PRD §3.2: "It is admitted only from `DURABILITY_COMPLETE`, and only when the family's `certified_emission_g_per_kwh` has actually been computed; the family advances to `SUBMITTED` and the submitting operator's identifier is retained as `submitted_by_user_id`."
        PRD §3.2: "On success the family moves `SUBMITTED → CERTIFIED`, `certified_by_user_id` records the certifying operator, `certified_at` is stamped from the clock, and every platform of the family has its posture recomputed to `OPEN`."

        Design: Corner/calculations/platform_posture_projection_follows_every_family_status
        """
        scenario = family_with_platform

        assert read_family(scenario.family_id)["status"] == "DRAFT"
        assert read_platform(scenario.platform_id)["certification_posture"] == "PENDING"

        run = schedule_durability_run(scenario.family_id, scenario.platform_id)
        assert read_family(scenario.family_id)["status"] == "DURABILITY_TESTING"
        assert (
            read_platform(scenario.platform_id)["certification_posture"] == "RESTRICTED"
        )

        complete_durability_run(run["id"])
        assert read_family(scenario.family_id)["status"] == "DURABILITY_COMPLETE"
        assert (
            read_platform(scenario.platform_id)["certification_posture"] == "RESTRICTED"
        )

        submit_family(scenario.family_id)
        assert read_family(scenario.family_id)["status"] == "SUBMITTED"
        assert (
            read_platform(scenario.platform_id)["certification_posture"] == "RESTRICTED"
        )

        certified = certify_family(scenario.family_id)
        assert certified["status"] == "CERTIFIED"
        assert read_platform(scenario.platform_id)["certification_posture"] == "OPEN"


class TestAuditSampleAndProgressCounters:
    """The audit sample and the progress counters both read settled units only."""

    def test_audit_sample_and_progress_count_only_settled_units(
        self,
        api,
        quality_engineer_headers,
        compliance_officer_headers,
        released_order_plant,
    ):
        """PRD §3.7: "Progress counters are always the plain counts they claim to be: `staged_quantity` is the number of the order's units whose `build_state` is `STAGED`, `ASSEMBLED` or `HOT_TESTED`, `built_quantity` is the number whose `build_state` is `RELEASED`, and a `CANCELLED` unit counts toward neither."
        PRD §3.7: "Cancellation moves `build_state` to the terminal `CANCELLED`, leaves `conformance_state` untouched, returns one piece to each of the carburetor and ignition lots by subtracting 1 from `consumed_qty` and adding 1 to `remaining_qty` on each, and subtracts 1 from the order's `staged_quantity`."
        PRD §3.8: "Its `required_sample_size` is the larger of 2 units and two percent of the order's `built_quantity` rounded **up** to a whole unit, and it is likewise frozen — later releases on the order do not enlarge it."
        PRD §3.8: "The sample must be at least as large as the frozen `required_sample_size`, else `ERR_AUDIT_SAMPLE_TOO_SMALL`, and it cannot exceed the order's `built_quantity`, else `ERR_AUDIT_SAMPLE_EXCEEDS_POPULATION`."
        PRD §3.7: "Units are readable individually and as a list, filterable by `build_order_id`, `machining_run_id`, `carburetor_lot_id`, `ignition_lot_id`, `build_state` and `conformance_state`."

        Design: Corner/calculations/audit_sample_and_progress_count_only_settled_units
        """
        scenario = released_order_plant

        build_and_release_unit(scenario, "SN-0001")
        still_staged = stage_engine_unit(scenario, "SN-0002")
        scrapped = stage_engine_unit(scenario, "SN-0003")
        cancelled = cancel_engine_unit(scrapped["id"])
        assert cancelled["build_state"] == "CANCELLED"

        order = scenario.refresh_build_order()
        assert order["built_quantity"] == 1
        assert order["staged_quantity"] == 1

        audit = schedule_line_audit(scenario.build_order_id, audit_week="2026-09-14")
        # max(2, ceil(1 * 0.02)) — the floor of 2 dominates.
        assert audit["required_sample_size"] == 2

        rows, meta = validate_paginated(
            api.list_engine_units(
                quality_engineer_headers,
                {
                    "build_order_id": scenario.build_order_id,
                    "build_state": "STAGED",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [still_staged["id"]]

        lot = read_lot(scenario.carburetor_lot_id)
        assert lot["consumed_qty"] == 2
        assert lot["remaining_qty"] == 798
        assert_lot_piece_conservation(lot)

        # Two units physically exist, but only one is in the audited population.
        validate_error(
            api.record_line_audit(
                audit["id"],
                {
                    "units_tested": 2,
                    "units_failed": 0,
                    "max_measured_emission_g_per_kwh": 5.60,
                },
                compliance_officer_headers,
            ),
            ApiErrorId.ERR_AUDIT_SAMPLE_EXCEEDS_POPULATION,
        )
