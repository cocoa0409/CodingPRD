# -*- coding: utf-8 -*-
"""Bench metrology, ISO zoning, remaining-life scoring and failure-cause coding."""
import pytest

from test_helpers import (
    ADMIN_1, ENG_1, FOUR_BANDS, INSP_1, ONE_BAND, ApiErrorId,
    accept_inspection, add_measurement, api_client as api, create_reading,
    credit_notes, inspect_order, open_inspection, read_core, read_customer,
    read_inspection, setup_shop, submit_inspection, validate_error,
    validate_paginated, validate_success,
)

EDGE_BAND = [dict(ONE_BAND[0])]


class TestClearanceBandEdges:

    def test_band_edges_are_inclusive_at_max_and_at_the_rework_shoulder(self):
        """PRD 3.4: "If the measured value is at least the lower bound and at most the upper
        bound — both edges are inclusive, so a reading landing exactly on either bound is in
        specification — then `band_result` is `IN_SPEC` and `deviation_ratio` is exactly 0."
        PRD 3.4: "If that excess is less than or equal to the band's `rework_extension_um`,
        `band_result` is `REWORKABLE`; if the excess is greater than the extension,
        `band_result` is `OUT_OF_SPEC`."
        PRD 3.4: "The reworkable shoulder is therefore inclusive of its far edge: a reading
        exactly one extension beyond the upper bound is still reworkable, and one micrometre
        further out is out of specification."

        Design: Difficulty/boundary_precision_check/clearance_band_edges_inclusive_at_max_and_rework_shoulder
        """
        world = setup_shop(account_code="EDG-001", customer_name="Edge Works",
                           asset_tag="FAN-01-GBX", model_code="EDGE-SPEC-1",
                           feature_bands=EDGE_BAND, serial_no="SN-EDG-1",
                           labor_hours=3.0)
        insp = open_inspection(world["order"]["id"])

        at_max = add_measurement(insp["id"], "BORE", 90)
        one_over = add_measurement(insp["id"], "BORE", 91)
        at_shoulder = add_measurement(insp["id"], "BORE", 105)
        past_shoulder = add_measurement(insp["id"], "BORE", 106)

        assert at_max["band_result"] == "IN_SPEC"
        assert at_max["deviation_ratio"] == pytest.approx(0.0, abs=1e-9)
        assert one_over["band_result"] == "REWORKABLE"
        assert one_over["deviation_ratio"] == pytest.approx(0.020000, abs=1e-9)
        assert at_shoulder["band_result"] == "REWORKABLE", (
            "90 + 15 = 105 um is exactly one extension out and is still reworkable"
        )
        assert past_shoulder["band_result"] == "OUT_OF_SPEC"

    def test_out_of_band_readings_carry_their_deviation_ratio_and_feature_score(self):
        """PRD 3.4: "For any reading outside the band, `deviation_ratio` is the excess divided
        by the band width, capped at 1, rounded half up to six decimal places."
        PRD 3.4: "Finally `feature_score` is one hundred multiplied by the quantity one minus
        `deviation_ratio`, rounded half up to six decimal places — so an in-specification
        reading scores exactly 100 and a reading a full band-width or more outside scores
        exactly 0."
        PRD 3.4: "The system stamps each reading with its owning `inspection_id`, taken from the
        path rather than the body, and with a `sequence_no`, a monotonic per-inspection counter
        starting at 1, which exists to break ties when two readings on the same feature share a
        creation instant."

        Design: Difficulty/boundary_precision_check/clearance_band_edges_inclusive_at_max_and_rework_shoulder
        """
        world = setup_shop(account_code="EDG-001", customer_name="Edge Works",
                           asset_tag="FAN-01-GBX", model_code="EDGE-SPEC-1",
                           feature_bands=EDGE_BAND, serial_no="SN-EDG-1",
                           labor_hours=3.0)
        insp = open_inspection(world["order"]["id"])

        rows = [add_measurement(insp["id"], "BORE", um) for um in (90, 91, 105, 106)]
        assert [row["sequence_no"] for row in rows] == [1, 2, 3, 4]

        past_shoulder = rows[3]
        assert past_shoulder["band_result"] == "OUT_OF_SPEC"
        assert past_shoulder["deviation_ratio"] == pytest.approx(0.320000, abs=1e-9), (
            "an excess of 16 um over a band width of 50 um is 0.32"
        )
        assert past_shoulder["feature_score"] == pytest.approx(68.000000, abs=1e-6)
        assert rows[0]["feature_score"] == pytest.approx(100.0, abs=1e-6)


class TestIsoSeverityZoning:

    def test_zone_floors_are_inclusive_at_their_lower_edge(self):
        """PRD 3.3: "The `iso_zone` is banded from `overall_velocity_mm_s` against three floors:
        a velocity below 1.40 is zone `A`; from 1.40 up to but not including 2.80 is zone `B`;
        from 2.80 up to but not including 4.50 is zone `C`; and 4.50 or above is zone `D`."
        PRD 3.3: "Each floor is inclusive at its lower edge, so a reading of exactly 2.80 is
        zone `C`, not zone `B`."

        Design: Difficulty/boundary_precision_check/iso_velocity_zone_floor_inclusive_at_four_point_five
        """
        world = setup_shop(account_code="EDG-002", customer_name="Edge Works",
                           asset_tag="FAN-02-GBX", with_order=False)
        asset_id = world["asset"]["id"]

        at_d = create_reading(asset_id, overall_velocity_mm_s=4.50,
                              bpfo_amplitude_g=0.20, bpfi_amplitude_g=0.20)
        just_under_d = create_reading(asset_id, reading_at="2026-08-02T06:05:00Z",
                                      overall_velocity_mm_s=4.49,
                                      bpfo_amplitude_g=0.20, bpfi_amplitude_g=0.20)
        at_c = create_reading(asset_id, reading_at="2026-08-02T06:10:00Z",
                              overall_velocity_mm_s=2.80,
                              bpfo_amplitude_g=0.20, bpfi_amplitude_g=0.20)
        just_under_b = create_reading(asset_id, reading_at="2026-08-02T06:15:00Z",
                                      overall_velocity_mm_s=1.39,
                                      bpfo_amplitude_g=0.20, bpfi_amplitude_g=0.20)

        assert at_d["iso_zone"] == "D"
        assert just_under_d["iso_zone"] == "C"
        assert at_c["iso_zone"] == "C"
        assert just_under_b["iso_zone"] == "A"

    def test_defect_ratios_divide_each_amplitude_by_the_same_baseline(self):
        """PRD 3.3: "Alongside the zone, `defect_ratio_outer` is the outer-race amplitude
        divided by the baseline amplitude and `defect_ratio_inner` is the inner-race amplitude
        divided by the same baseline, each rounded half up to six decimal places."
        PRD 3.3: "A vibration reading is a historical observation and is never revised: it
        carries only its `id` and `created_at`."

        Design: Difficulty/boundary_precision_check/iso_velocity_zone_floor_inclusive_at_four_point_five
        """
        world = setup_shop(account_code="EDG-002", customer_name="Edge Works",
                           asset_tag="FAN-02-GBX", with_order=False)
        reading = create_reading(world["asset"]["id"], overall_velocity_mm_s=4.50,
                                 bpfo_amplitude_g=0.20, bpfi_amplitude_g=0.20,
                                 baseline_amplitude_g=0.20)
        assert reading["iso_zone"] == "D"
        assert reading["defect_ratio_outer"] == pytest.approx(1.000000, abs=1e-9)
        assert reading["defect_ratio_inner"] == pytest.approx(1.000000, abs=1e-9)
        assert "updated_at" not in reading and "version" not in reading


class TestSubmissionPreconditions:

    def test_submit_with_no_measurements_at_all_is_measurements_incomplete(self):
        """PRD 3.5: "And every `feature_code` listed in the governing spec's
        `required_feature_codes` must carry at least one measurement on this inspection; any
        shortfall, including an inspection with no measurements at all, is
        `ERR_MEASUREMENTS_INCOMPLETE` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/inspection_submit_with_empty_measurement_set_is_rejected
        """
        world = setup_shop(account_code="EDG-003", customer_name="Edge Works",
                           asset_tag="FAN-03-GBX", model_code="EDGE-SPEC-3",
                           feature_bands=EDGE_BAND, serial_no="SN-EDG-3",
                           labor_hours=3.0)
        reading = create_reading(world["asset"]["id"])
        insp = open_inspection(world["order"]["id"],
                               linked_vibration_reading_id=reading["id"])

        resp = api.advance_inspection(insp["id"], {"action": "SUBMIT"}, INSP_1)
        error = validate_error(resp, ApiErrorId.ERR_MEASUREMENTS_INCOMPLETE.value, 422)
        assert error["error_id"] != ApiErrorId.ERR_VIBRATION_LINK_REQUIRED.value, (
            "the reading is linked precisely so the earlier check cannot mask this one"
        )

        _, meta = validate_paginated(api.list_measurements(insp["id"], ADMIN_1))
        assert meta["total_count"] == 0

    def test_rejected_submission_writes_no_grading_output(self):
        """PRD 3.5: "Only an `Inspector` may submit. On success the caller's `X-User-ID` is
        recorded as `submitted_by_user_id`, both computations below run, and `status` becomes
        `SUBMITTED`."
        PRD 3.5: "any shortfall, including an inspection with no measurements at all, is
        `ERR_MEASUREMENTS_INCOMPLETE` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/inspection_submit_with_empty_measurement_set_is_rejected
        """
        world = setup_shop(account_code="EDG-003", customer_name="Edge Works",
                           asset_tag="FAN-03-GBX", model_code="EDGE-SPEC-3",
                           feature_bands=EDGE_BAND, serial_no="SN-EDG-3",
                           labor_hours=3.0)
        reading = create_reading(world["asset"]["id"])
        insp = open_inspection(world["order"]["id"],
                               linked_vibration_reading_id=reading["id"])

        validate_error(api.advance_inspection(insp["id"], {"action": "SUBMIT"}, INSP_1),
                       ApiErrorId.ERR_MEASUREMENTS_INCOMPLETE.value, 422)

        after = read_inspection(insp["id"])
        assert after["status"] == "DRAFT"
        assert after["remaining_life_score"] is None
        assert after["remaining_life_grade"] is None
        assert after["submitted_by_user_id"] is None

    def test_submit_without_any_linked_reading_and_cross_asset_link_are_rejected(self):
        """PRD 3.5: "It must have a linked vibration reading — and the submitting call may
        itself supply `linked_vibration_reading_id` to satisfy this, so the test is against the
        value in force after the call's own input is applied; if none is in force the rejection
        is `ERR_VIBRATION_LINK_REQUIRED` (HTTP 422)."
        PRD 3.4: "the reading's `customer_asset_id` must equal the order's `customer_asset_id`,
        and a cross-asset link is rejected with `ERR_VIBRATION_ASSET_MISMATCH`."

        Design: Corner/errors/vibration_link_required_and_asset_mismatch_are_rejected
        """
        world = setup_shop(account_code="VIB-001", customer_name="Link Mill",
                           asset_tag="VIB-01-GBX", serial_no="SN-VIB-1", labor_hours=4.0)
        other_asset = validate_success(api.create_asset(
            world["customer"]["id"],
            {"asset_tag": "VIB-02-GBX", "criticality": "STANDARD",
             "duty_class": "CONTINUOUS"}, ADMIN_1), 201)
        stray_reading = create_reading(other_asset["id"])

        insp = open_inspection(world["order"]["id"])
        add_measurement(insp["id"], "BORE", 85)

        validate_error(api.advance_inspection(insp["id"], {"action": "SUBMIT"}, INSP_1),
                       ApiErrorId.ERR_VIBRATION_LINK_REQUIRED.value, 422)
        assert read_inspection(insp["id"])["status"] == "DRAFT"

        validate_error(api.create_inspection(
            {"rebuild_order_id": world["order"]["id"],
             "linked_vibration_reading_id": stray_reading["id"]}, INSP_1),
            ApiErrorId.ERR_VIBRATION_ASSET_MISMATCH.value, 409)

        _, meta = validate_paginated(api.list_inspections(
            ADMIN_1, params={"rebuild_order_id": world["order"]["id"]}))
        assert meta["total_count"] == 1


class TestRemainingLifeVariants:

    def test_critical_asset_selects_the_conservative_minimum_aggregation(self):
        """PRD 3.5: "The composite aggregation multiplies each governing measurement's
        `feature_score` by its band's `weight`, sums those products, and divides by the sum of
        the weights — a weighted average, in which one bad feature is diluted by healthy
        siblings."
        PRD 3.5: "Which one governs is pinned by the destination machine: when the order's
        asset has a `criticality` of `CRITICAL`, `life_score_variant` is `CONSERVATIVE` and the
        conservative aggregation is the base; otherwise `life_score_variant` is `COMPOSITE` and
        the weighted average is the base."
        PRD 3.5: "The base aggregation is first rounded half up to a whole number, and only then
        are two integer penalties subtracted from it."

        Design: Difficulty/combinatorial_formula/life_score_conservative_min_vs_composite_weighted_average
        """
        world = setup_shop(account_code="NGM-003", asset_tag="PUMP-11-GBX",
                           criticality="CRITICAL", feature_bands=FOUR_BANDS,
                           serial_no="SN-77003", rebuild_count=1,
                           declared_condition_grade="GRADE_D", labor_hours=6.5)
        inspect_order(world)

        insp = read_inspection(world["inspection"]["id"])
        assert insp["life_score_variant"] == "CONSERVATIVE"
        assert insp["remaining_life_score"] == 79, (
            "the worst feature scores 90; 90 less the zone-B 5 and the rebuild 6 is 79"
        )
        assert insp["remaining_life_grade"] == "GRADE_B"

    def test_conservative_grade_carries_into_a_lower_exchange_core_credit(self):
        """PRD 3.5: "On identical metrology the conservative variant yields a score less than or
        equal to the composite one, and can drop a core a whole grade band."
        PRD 3.6: "Caused by that, the core takes on the bench verdict: its `condition_grade` is
        set from the inspection's `remaining_life_grade`, its status moves `INSPECTING →
        GRADED`, and its `final_core_credit_cents` is computed."

        Design: Difficulty/combinatorial_formula/life_score_conservative_min_vs_composite_weighted_average
        """
        world = setup_shop(account_code="NGM-003", asset_tag="PUMP-11-GBX",
                           criticality="CRITICAL", feature_bands=FOUR_BANDS,
                           serial_no="SN-77003", rebuild_count=1,
                           declared_condition_grade="GRADE_D", labor_hours=6.5)
        inspect_order(world)

        core = read_core(world["core"]["id"])
        assert core["condition_grade"] == "GRADE_B"
        assert core["final_core_credit_cents"] == 58950, (
            "round(90000 * 0.75) = 67500, less 7200 decay, less the 1350 REWORKABLE line"
        )
        customer = read_customer(world["customer"]["id"])
        assert customer["total_credit_balance_cents"] == 58950


class TestDeductionRounding:

    ROUND_BANDS = [
        {"feature_code": "BORE", "min_um": 40, "max_um": 90,
         "rework_extension_um": 15, "deduction_pct": 0.2468, "weight": 0.40},
        {"feature_code": "JOURNAL", "min_um": 25, "max_um": 60,
         "rework_extension_um": 10, "deduction_pct": 0.2468, "weight": 0.30},
        {"feature_code": "HOUSING_FIT", "min_um": 10, "max_um": 45,
         "rework_extension_um": 10, "deduction_pct": 0.2468, "weight": 0.30},
    ]

    def _rounding_world(self):
        world = setup_shop(account_code="RND-001", customer_name="Rounding Works",
                           asset_tag="MIX-02-GBX", duty_class="INTERMITTENT",
                           model_code="ROUND-TEST-1", feature_bands=self.ROUND_BANDS,
                           standard_overrides={"base_core_value_cents": 1000},
                           serial_no="SN-RND-1", rebuild_count=0,
                           declared_condition_grade="GRADE_A", labor_hours=2.0)
        inspect_order(
            world,
            measurements=(("BORE", 91), ("JOURNAL", 61), ("HOUSING_FIT", 46)),
            reading_overrides={"overall_velocity_mm_s": 1.00,
                               "bpfo_amplitude_g": 0.10, "bpfi_amplitude_g": 0.10},
        )
        return world

    def test_three_reworkable_lines_round_individually_before_they_are_summed(self):
        """PRD 3.6: "A measurement whose `band_result` is `REWORKABLE` contributes the same
        product taken at half strength — the base value multiplied by the percentage multiplied
        by one half — again rounded half up on that line alone."
        PRD 3.6: "Those already-rounded lines are then added together. Summing the unrounded
        products and rounding once at the end is explicitly not the rule and produces different
        cents."
        PRD 2.6: "When this document says that individual lines are rounded and then summed,
        summing first and rounding once is not an acceptable substitute: the two procedures
        produce different cents, and the tests distinguish them."

        Design: Difficulty/combinatorial_formula/core_credit_rounds_each_deduction_line_before_summing
        """
        world = self._rounding_world()
        core = read_core(world["core"]["id"])
        assert core["provisional_core_credit_cents"] == 1000
        assert core["final_core_credit_cents"] == 631, (
            "three lines of 123.4 cents each round to 123 for a deduction total of 369"
        )
        assert core["final_core_credit_cents"] != 630, (
            "630 is the sum-then-round answer and is explicitly not the rule"
        )

    def test_the_rounded_deduction_total_lands_on_the_customer_ledger(self):
        """PRD 3.5: "That score is then banded into `remaining_life_grade` against four
        inclusive floors: a score of 80 or more is `GRADE_A`, 60 or more is `GRADE_B`, 35 or
        more is `GRADE_C`, 15 or more is `GRADE_D`, and anything below 15 is `SCRAP`."
        PRD 2.9: "`core_credit_balance_cents` is the sum of `amount_cents` over the customer's
        `POSTED` notes whose `kind` is `CORE_EXCHANGE`"

        Design: Difficulty/combinatorial_formula/core_credit_rounds_each_deduction_line_before_summing
        """
        world = self._rounding_world()
        insp = read_inspection(world["inspection"]["id"])
        assert insp["remaining_life_score"] == 97
        assert insp["remaining_life_grade"] == "GRADE_A"

        customer = read_customer(world["customer"]["id"])
        assert customer["core_credit_balance_cents"] == 631
        assert customer["total_credit_balance_cents"] == 631


class TestGoverningMeasurementSelection:

    def test_the_latest_reading_on_a_feature_governs_both_computations(self):
        """PRD 3.5: "For each distinct `feature_code` that has at least one measurement on
        *this* inspection, the governing measurement is the one with the greatest `created_at`;
        where two share that instant, the one with the greater `sequence_no` governs."
        PRD 3.6: "A measurement whose `band_result` is `OUT_OF_SPEC` contributes
        `base_core_value_cents` multiplied by that percentage, **rounded half up to whole cents
        on that line alone**."

        Design: Corner/calculations/governing_measurement_is_the_latest_by_created_at_then_sequence_no
        """
        world = setup_shop(account_code="GOV-001", customer_name="Governing Mill",
                           asset_tag="GOV-01-GBX", serial_no="SN-GOV-1",
                           declared_condition_grade="GRADE_B", labor_hours=3.0)
        inspect_order(world, measurements=(("BORE", 85), ("BORE", 200)),
                      reading_overrides={"overall_velocity_mm_s": 1.00,
                                         "bpfo_amplitude_g": 0.10,
                                         "bpfi_amplitude_g": 0.10})

        insp = read_inspection(world["inspection"]["id"])
        assert insp["remaining_life_score"] == 0
        assert insp["remaining_life_grade"] == "SCRAP"
        assert insp["life_score_variant"] == "COMPOSITE"

        core = read_core(world["core"]["id"])
        assert core["condition_grade"] == "SCRAP"
        assert core["final_core_credit_cents"] == 0
        assert read_customer(world["customer"]["id"])["core_credit_balance_cents"] == 0

        rows, meta = validate_paginated(
            api.list_measurements(world["inspection"]["id"], ADMIN_1))
        assert meta["total_count"] == 2
        assert sorted(row["sequence_no"] for row in rows) == [1, 2]


class TestFailureCauseLadder:

    def test_the_ladder_stops_at_the_first_matching_clause(self):
        """PRD 3.5: "Second: if the linked reading's `defect_ratio_outer` is at least 3.0 and is
        also greater than or equal to its `defect_ratio_inner`, the code is `OUTER_RACE_SPALL`
        with confidence `HIGH`."
        PRD 3.5: "Third: if the reading's `defect_ratio_inner` is at least 3.0, the code is
        `INNER_RACE_SPALL` with confidence `HIGH`."
        PRD 3.5: "The ordering of those two clauses is the pinned tie-break — when the two
        ratios are exactly equal and both clear the floor of 3.0, the outer race wins."
        PRD 3.5: "Fourth: if the reading's `iso_zone` is `D`, the code is `MISALIGNMENT` with
        confidence `MEDIUM`."

        Design: Corner/calculations/failure_cause_ladder_selects_the_first_matching_clause
        """
        world = setup_shop(account_code="COD-001", customer_name="Coding Mill",
                           asset_tag="COD-01-GBX", serial_no="SN-COD-1",
                           declared_condition_grade="GRADE_B", labor_hours=3.0)
        asset_id, order_id = world["asset"]["id"], world["order"]["id"]

        vr_outer = create_reading(asset_id, overall_velocity_mm_s=3.2,
                                  bpfo_amplitude_g=0.9, bpfi_amplitude_g=0.3)
        vr_tie = create_reading(asset_id, reading_at="2026-08-02T06:05:00Z",
                                overall_velocity_mm_s=3.2,
                                bpfo_amplitude_g=0.6, bpfi_amplitude_g=0.6)
        vr_inner = create_reading(asset_id, reading_at="2026-08-02T06:10:00Z",
                                  overall_velocity_mm_s=3.2,
                                  bpfo_amplitude_g=0.3, bpfi_amplitude_g=0.9)
        vr_mis = create_reading(asset_id, reading_at="2026-08-02T06:15:00Z",
                                overall_velocity_mm_s=4.6,
                                bpfo_amplitude_g=0.2, bpfi_amplitude_g=0.2)

        outcomes = {}
        for label, reading in (("outer", vr_outer), ("tie", vr_tie),
                               ("inner", vr_inner), ("mis", vr_mis)):
            insp = open_inspection(order_id, linked_vibration_reading_id=reading["id"])
            add_measurement(insp["id"], "BORE", 85)
            outcomes[label] = submit_inspection(insp["id"])

        assert vr_tie["defect_ratio_outer"] == pytest.approx(3.000000, abs=1e-9)
        assert vr_tie["defect_ratio_inner"] == pytest.approx(3.000000, abs=1e-9)

        assert outcomes["outer"]["failure_cause_code"] == "OUTER_RACE_SPALL"
        assert outcomes["outer"]["cause_confidence"] == "HIGH"
        assert outcomes["tie"]["failure_cause_code"] == "OUTER_RACE_SPALL"
        assert outcomes["tie"]["cause_confidence"] == "HIGH"
        assert outcomes["inner"]["failure_cause_code"] == "INNER_RACE_SPALL"
        assert outcomes["inner"]["cause_confidence"] == "HIGH"
        assert outcomes["mis"]["failure_cause_code"] == "MISALIGNMENT"
        assert outcomes["mis"]["cause_confidence"] == "MEDIUM"

        assert outcomes["outer"]["remaining_life_score"] == 85
        assert outcomes["outer"]["remaining_life_grade"] == "GRADE_A"
        assert outcomes["mis"]["remaining_life_score"] == 70
        assert outcomes["mis"]["remaining_life_grade"] == "GRADE_B"
