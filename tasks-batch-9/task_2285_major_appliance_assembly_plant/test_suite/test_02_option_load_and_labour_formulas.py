"""Formulas whose step order is observable: the option-load cap, the efficiency
index and the fatigue-multiplied labour commitment.

Each of the three is a product or a chain of roundings where doing the steps in a
different order produces a different, wrong answer that the assertions pin down.
"""

from test_helpers import (
    PRODUCTION_PLANNER_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
    ApiErrorId,
    BuildSlotStatus,
    CertificationTier,
    QualityStatus,
    add_fam_b_variant,
    approx2,
    base_plant,
    base_plant_with_shift,
    gated_unit,
    new_shift_plan,
    planned_slot,
    plain_variant,
    read_shift_plan,
    read_slot,
    read_station,
    sequence_many,
    sequence_slot,
    validate_error,
    validate_success,
)


def _load_window_plant(api):
    """Three eight-point slots sequenced, then a four- and a five-point slot.

    Staffing 18 operators against a baseline of 20 makes the cap 28, and the
    window from index 1 through index 5 already holds 24 points.
    """
    plant = base_plant(api)
    wm_p = plain_variant(api, plant, "WM-P", 8, 60, option_codes=["OPT-A", "OPT-B"])
    wm_r = plain_variant(api, plant, "WM-R", 4, 60, option_codes=["OPT-A"])
    wm_q = plain_variant(api, plant, "WM-Q", 5, 60, option_codes=["OPT-A", "OPT-C"])
    plant.shift_plan = new_shift_plan(api, plant.line_id, planned_headcount=18)
    sequence_many(api, plant, [
        (1, "2026-08-03T07:00:00Z", wm_p["id"]),
        (2, "2026-08-03T07:10:00Z", wm_p["id"]),
        (3, "2026-08-03T07:20:00Z", wm_p["id"]),
    ])
    planned_slot(api, plant, 4, "2026-08-03T07:30:00Z", wm_r["id"])
    planned_slot(api, plant, 5, "2026-08-03T07:40:00Z", wm_q["id"])
    return plant


class TestOptionLoadWindowCap:
    """The cap is one floor applied once to the product of four factors."""

    def test_window_totalling_exactly_twenty_eight_points_is_admitted(self, api):
        """A four-point slot fills the window to 24 + 4 = 28 and sequences.

        "On a line whose `option_load_limit_pct` is 63.00 and whose
        `baseline_headcount` is 20, covered by a plan staffing 18 operators, the
        staffing factor is 0.9000; five times 0.63 times ten times 0.9000 is
        28.35, and rounding down once gives a cap of 28."

        Design: Difficulty/combinatorial_formula/option_load_cap_single_floor_over_all_four_factors
        """
        plant = _load_window_plant(api)

        slot = validate_success(
            api.sequence_build_slot(plant.slot_id(4), PRODUCTION_PLANNER_HEADERS)
        )

        assert slot["status"] == BuildSlotStatus.SEQUENCED.value
        assert slot["option_points_snapshot"] == 4
        # A cap computed by flooring the percentage factor first would be 27 and
        # would have refused this slot.
        assert read_station(api, plant.st10_id)["presentation_slots_used"] == 4

    def test_window_totalling_twenty_nine_points_is_rejected_and_writes_nothing(self, api):
        """A five-point slot would make 29 and is refused with nothing written.

        "A window totalling exactly 28 option points is admitted; a window
        totalling 29 is rejected."

        Design: Difficulty/combinatorial_formula/option_load_cap_single_floor_over_all_four_factors
        """
        plant = _load_window_plant(api)
        sequence_slot(api, plant.slot_id(4))
        validate_success(
            api.de_sequence_build_slot(plant.slot_id(4), PRODUCTION_PLANNER_HEADERS)
        )

        response = api.sequence_build_slot(plant.slot_id(5), PRODUCTION_PLANNER_HEADERS)
        validate_error(response, ApiErrorId.ERR_OPTION_LOAD_WINDOW_EXCEEDED)

        rejected = read_slot(api, plant.slot_id(5))
        assert rejected["status"] == BuildSlotStatus.PLANNED.value
        assert rejected["option_points_snapshot"] is None
        assert read_station(api, plant.st10_id)["presentation_slots_used"] == 3


class TestEfficiencyRatioRoundingOrder:
    """Each ratio is rounded before the weights are applied."""

    def test_index_is_zero_point_nine_five_not_zero_point_nine_six(self, api):
        """413.96 kWh and 168.98 litres certify at 0.95, not at 0.96.

        "With a single energy test measuring 413.96 against a limit of 400.00 and
        a single water test measuring 168.98 against a limit of 200.00, the pinned
        order gives ratios of 1.03 and 0.84, a weighted sum of 0.954, and an index
        of 0.95 — tier `A`."

        Design: Difficulty/combinatorial_formula/efficiency_ratios_rounded_before_weighting
        """
        plant = base_plant_with_shift(api)
        unit = gated_unit(api, plant, 1, energy=[413.96], water=[168.98])

        certified = validate_success(
            api.certify_unit(unit["id"], QUALITY_INSPECTOR_HEADERS)
        )

        assert float(certified["efficiency_index"]) == approx2(0.95)
        assert float(certified["efficiency_index"]) != approx2(0.96)
        assert certified["quality_status"] == QualityStatus.CERTIFIED.value

    def test_rounding_order_decides_the_certification_tier(self, api):
        """The same measurements land in tier A rather than tier B.

        "Weighting the unrounded 1.0349 and 0.8449 would give 0.9589 and an index
        of 0.96 — tier `B` — which is wrong."

        Design: Difficulty/combinatorial_formula/efficiency_ratios_rounded_before_weighting
        """
        plant = base_plant_with_shift(api)
        unit = gated_unit(api, plant, 1, energy=[413.96], water=[168.98])

        certified = validate_success(
            api.certify_unit(unit["id"], QUALITY_INSPECTOR_HEADERS)
        )

        assert certified["certification_tier"] == CertificationTier.A.value
        assert certified["certification_tier"] != CertificationTier.B.value


class TestFatigueTierOnGrossMinutes:
    """The tier is chosen after the changeover minutes are added in."""

    def test_two_family_run_commits_three_hundred_and_twenty_nine_minutes(self, api):
        """295 unit minutes plus an 18-minute changeover commit 329 minutes.

        "Both the tier selection and the multiplication use the **gross** total,
        changeover minutes included: a plan holding a 150-minute unit of one family
        at index 1 and a 145-minute unit of another family at index 2 on a line
        tooled for the first family has `unit_labor_minutes` of 295 and
        `changeover_minutes` of 18, so the gross total is 313; because 313 exceeds
        the 300-minute tier boundary the multiplier is 1.05, and the committed
        figure is 313 multiplied by 1.05, which is 328.65, rounded up to 329."

        Design: Difficulty/combinatorial_formula/fatigue_tier_selected_on_gross_including_changeover
        """
        plant = base_plant_with_shift(api)
        sequence_many(api, plant, [(1, "2026-08-03T07:00:00Z", plant.variant_id)])
        wm_y = add_fam_b_variant(api, plant)
        planned_slot(api, plant, 2, "2026-08-03T08:00:00Z", wm_y["id"])

        validate_success(
            api.sequence_build_slot(plant.slot_id(2), PRODUCTION_PLANNER_HEADERS)
        )

        plan = read_shift_plan(api, plant.shift_plan_id)
        assert plan["unit_labor_minutes"] == 295
        assert plan["changeover_minutes"] == 18
        assert plan["committed_labor_minutes"] == 329

    def test_committed_figure_is_neither_the_gross_nor_the_pre_changeover_tier(self, api):
        """329 falsifies both of the wrong step orders at once.

        "Choosing the tier from the 295 unit minutes alone, or applying the
        multiplier to the unit minutes and adding changeover afterwards, both yield
        different answers and are wrong."

        Design: Difficulty/combinatorial_formula/fatigue_tier_selected_on_gross_including_changeover
        """
        plant = base_plant_with_shift(api)
        sequence_many(api, plant, [(1, "2026-08-03T07:00:00Z", plant.variant_id)])
        wm_y = add_fam_b_variant(api, plant)
        planned_slot(api, plant, 2, "2026-08-03T08:00:00Z", wm_y["id"])

        slot = validate_success(
            api.sequence_build_slot(plant.slot_id(2), PRODUCTION_PLANNER_HEADERS)
        )

        plan = read_shift_plan(api, plant.shift_plan_id)
        assert slot["status"] == BuildSlotStatus.SEQUENCED.value
        assert plan["available_labor_minutes"] == 480
        assert plan["committed_labor_minutes"] != 313
        assert plan["committed_labor_minutes"] != 328
