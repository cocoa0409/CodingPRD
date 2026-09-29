"""Boundaries of the plant's four derived quantities.

The option-load cap is evaluated per rolling window rather than over the whole
line, the presentation charge is a ceiling that can exceed a small station
outright, the fatigue tier boundary is inclusive, the certification tier bands
are inclusive at their tops, and a part with no returns reports honest zeroes.
"""

from test_helpers import (
    BASE_CLOCK,
    PRODUCTION_PLANNER_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
    ApiErrorId,
    BuildSlotStatus,
    CertificationTier,
    LinePosture,
    PartLifecycleStatus,
    Plant,
    QualityStatus,
    approx2,
    base_plant_with_shift,
    gated_unit,
    new_line,
    new_part,
    new_shift_plan,
    new_station,
    new_supplier,
    plain_variant,
    plan_many,
    planned_slot,
    read_line,
    read_part,
    read_shift_plan,
    read_slot,
    read_station,
    read_unit,
    read_warranty_metrics,
    sequence_many,
    sequence_slot,
    set_clock,
    shipped_unit,
    validate_error,
    validate_success,
)


def _line_whose_only_station_holds_one_presentation_slot(api):
    """A line with one station offering a single presentation slot.

    The variant scheduled on it draws two door panels, and two door panels
    charge two presentation units, so the position cannot be hosted at all.
    """
    plant = Plant()
    set_clock(api, BASE_CLOCK)
    plant.line = new_line(api, "L3")
    station = new_station(api, plant.line_id, "ST-N", 10,
                          presentation_slot_capacity=1, station_cycle_seconds=110)
    plant.stations["ST-N"] = station
    plant.supplier = new_supplier(api, "SUP1", "Hinge and Module Co",
                                  sync_window_minutes=30)
    plant.parts["P-DOOR-A"] = new_part(api, plant.supplier_id, "P-DOOR-A",
                                       is_sequenced_module=False,
                                       line_side_max_units=24)
    variant = plain_variant(api, plant, "WM-N", 2, 100, part_id=plant.part_id,
                            station_id=station["id"], qty_per_unit=2)
    plant.shift_plan = new_shift_plan(api, plant.line_id, planned_headcount=20)
    slot = planned_slot(api, plant, 1, "2026-08-03T07:00:00Z",
                        variant_id=variant["id"])
    return plant, station, slot


class TestOptionLoadWindow:
    """Only five consecutive indexes are ever weighed against the cap."""

    def test_the_binding_window_admits_a_sixth_slot_a_whole_line_sum_would_refuse(
            self, api):
        """Thirty points inside the window pass; a later window of thirty-two does not.

        "The points in a window are the sum of `option_points_snapshot` over the line's
        slots whose `sequence_index` falls inside the window and whose `status` is
        `SEQUENCED`, `RELEASED` or `BUILT`, plus the candidate variant's own
        `option_content_points`."

        "The slot is admissible only when every one of the five windows is at or below
        the cap; otherwise `ERR_OPTION_LOAD_WINDOW_EXCEEDED`."

        Design: Corner/calculations/option_load_window_counts_only_the_five_slot_rolling_window
        """
        plant = base_plant_with_shift(api)
        light = plain_variant(api, plant, "WM-L", 6, 50)
        heavy = plain_variant(api, plant, "WM-P", 8, 50, option_codes=["OPT-A", "OPT-B"])
        sequence_many(api, plant, [
            (1, "2026-08-03T07:00:00Z", light["id"]),
            (2, "2026-08-03T07:10:00Z", light["id"]),
            (3, "2026-08-03T07:20:00Z", light["id"]),
            (4, "2026-08-03T07:30:00Z", light["id"]),
            (5, "2026-08-03T07:40:00Z", light["id"]),
        ])
        plan_many(api, plant, [
            (6, "2026-08-03T07:50:00Z", light["id"]),
            (7, "2026-08-03T08:00:00Z", heavy["id"]),
        ])

        # Window [2..6] totals four sequenced sixes plus the candidate's six: 30.
        admitted = validate_success(
            api.sequence_build_slot(plant.slot_id(6), PRODUCTION_PLANNER_HEADERS)
        )

        assert admitted["status"] == BuildSlotStatus.SEQUENCED.value
        assert admitted["option_points_snapshot"] == 6
        assert admitted["allocated_slot_units"] == 1
        plan = read_shift_plan(api, plant.shift_plan_id)
        assert plan["unit_labor_minutes"] == 300
        assert plan["changeover_minutes"] == 0
        assert plan["committed_labor_minutes"] == 300
        assert read_station(api, plant.st10_id)["presentation_slots_used"] == 6
        assert float(read_line(api, plant.line_id)["free_slot_pct"]) == approx2(92.50)

        # Window [3..7] totals four sequenced sixes plus the candidate's eight: 32.
        validate_error(
            api.sequence_build_slot(plant.slot_id(7), PRODUCTION_PLANNER_HEADERS),
            ApiErrorId.ERR_OPTION_LOAD_WINDOW_EXCEEDED,
            expected_status=422,
        )

        assert read_slot(api, plant.slot_id(7))["status"] == BuildSlotStatus.PLANNED.value
        assert read_shift_plan(api, plant.shift_plan_id)["committed_labor_minutes"] == 300


class TestPresentationAllocationCeiling:
    """The charge is a ceiling, so a small station can be unusable outright."""

    def test_a_position_needing_two_units_cannot_be_hosted_by_a_one_slot_station(
            self, api):
        """The abort happens before anything is charged anywhere.

        "The first station at which the existing `presentation_slots_used` plus the new
        charge would exceed its `presentation_slot_capacity` aborts the entire
        sequencing attempt with `ERR_PRESENTATION_SLOTS_EXHAUSTED`, and **no** station
        is charged."

        Design: Corner/calculations/presentation_allocation_ceiling_exhausts_a_one_slot_station
        """
        plant, station, slot = _line_whose_only_station_holds_one_presentation_slot(api)

        validate_error(
            api.sequence_build_slot(slot["id"], PRODUCTION_PLANNER_HEADERS),
            ApiErrorId.ERR_PRESENTATION_SLOTS_EXHAUSTED,
            expected_status=422,
        )

        assert read_station(api, station["id"])["presentation_slots_used"] == 0
        line = read_line(api, plant.line_id)
        assert line["presentation_slots_total"] == 1
        assert line["presentation_slots_committed"] == 0
        assert float(line["free_slot_pct"]) == approx2(100.00)
        assert line["posture"] == LinePosture.OPEN.value
        untouched = read_slot(api, slot["id"])
        assert untouched["status"] == BuildSlotStatus.PLANNED.value
        assert untouched["presentation_allocations"] == []
        assert read_shift_plan(api, plant.shift_plan_id)["committed_labor_minutes"] == 0


class TestFatigueTierBoundary:
    """Three hundred gross minutes is the last minute of the flat tier."""

    def test_one_more_minute_of_work_costs_seventeen_committed_minutes(self, api):
        """Gross 300 commits 300; gross 301 commits 317.

        "The multiplier is 1.00 when the gross total is at most 300 minutes, 1.05 when
        it is at most 450 minutes, and 1.12 above that. The committed figure is the
        gross total multiplied by that multiplier, rounded up to a whole minute once,
        at the end."

        Design: Corner/calculations/fatigue_tier_boundary_at_exactly_three_hundred_gross_minutes
        """
        plant = base_plant_with_shift(api)
        trim = plain_variant(api, plant, "WM-T", 1, 1)
        sequence_many(api, plant, [
            (1, "2026-08-03T07:00:00Z", None),
            (2, "2026-08-03T07:30:00Z", None),
        ])
        planned_slot(api, plant, 3, "2026-08-03T08:00:00Z", variant_id=trim["id"])

        flat = read_shift_plan(api, plant.shift_plan_id)
        assert flat["unit_labor_minutes"] == 300
        assert flat["changeover_minutes"] == 0
        assert flat["committed_labor_minutes"] == 300

        sequenced = sequence_slot(api, plant.slot_id(3))

        assert sequenced["status"] == BuildSlotStatus.SEQUENCED.value
        assert sequenced["labor_minutes_snapshot"] == 1
        assert sequenced["option_points_snapshot"] == 1
        tiered = read_shift_plan(api, plant.shift_plan_id)
        assert tiered["unit_labor_minutes"] == 301
        assert tiered["changeover_minutes"] == 0
        assert tiered["committed_labor_minutes"] == 317
        assert tiered["available_labor_minutes"] == 480
        assert read_station(api, plant.st10_id)["presentation_slots_used"] == 5
        assert float(read_line(api, plant.line_id)["free_slot_pct"]) == approx2(93.75)


class TestCertificationTierBands:
    """The band tops are inclusive, decided on the two-decimal index."""

    def test_an_index_of_exactly_eighty_hundredths_is_a_plus_and_one_more_is_a(self, api):
        """The same weights, one hundredth apart, land in different tiers.

        "The tier is then read off the two-decimal index: an index of at most 0.80 is
        `A_PLUS`, at most 0.95 is `A`, and at most 1.00 is `B`. An index above 1.00 is
        not certifiable at all."

        Design: Corner/calculations/efficiency_index_at_tier_a_plus_boundary_and_one_hundredth_above
        """
        plant = base_plant_with_shift(api)
        first = gated_unit(api, plant, 1, energy=[320.00], water=[160.00])
        second = gated_unit(api, plant, 2, "2026-08-03T07:30:00Z", safety=0.31,
                            leak=1.20, energy=[324.00], water=[160.00])
        # Each type has exactly one recorded test, so both variants agree here.
        assert float(read_unit(api, first["id"])["provisional_efficiency_index"]) == \
            approx2(0.80)
        assert float(read_unit(api, second["id"])["provisional_efficiency_index"]) == \
            approx2(0.81)

        top_of_band = validate_success(
            api.certify_unit(first["id"], QUALITY_INSPECTOR_HEADERS)
        )
        one_hundredth_above = validate_success(
            api.certify_unit(second["id"], QUALITY_INSPECTOR_HEADERS)
        )

        assert float(top_of_band["efficiency_index"]) == approx2(0.80)
        assert top_of_band["certification_tier"] == CertificationTier.A_PLUS.value
        assert top_of_band["quality_status"] == QualityStatus.CERTIFIED.value
        assert float(one_hundredth_above["efficiency_index"]) == approx2(0.81)
        assert one_hundredth_above["certification_tier"] == CertificationTier.A.value
        assert one_hundredth_above["quality_status"] == QualityStatus.CERTIFIED.value


class TestWarrantyMetricsBeforeAnyReturn:
    """The denominator exists before the numerator does."""

    def test_a_shipped_cohort_with_no_returns_reports_zero_rates(self, api):
        """One cohort unit, no failures, both rates flat zero and nothing breached.

        "A zero denominator in either variant yields 0.00 and never triggers anything."

        "The metrics response reports `part_id`, `failure_count`, `cohort_units`,
        `total_field_hours`, `cohort_failure_rate_per_1000`,
        `shipped_exposure_rate_per_1000`, `trigger_threshold` — which is 8.00 — and
        `trigger_breached`, a boolean reflecting the production-cohort variant alone."

        Design: Corner/calculations/warranty_metrics_read_is_all_zero_before_any_return
        """
        plant = base_plant_with_shift(api)
        shipped_unit(api, plant, 1)

        metrics = read_warranty_metrics(api, plant.part_id)

        assert metrics["part_id"] == plant.part_id
        assert metrics["failure_count"] == 0
        assert metrics["cohort_units"] == 1
        assert float(metrics["total_field_hours"]) == approx2(0.00)
        assert float(metrics["cohort_failure_rate_per_1000"]) == approx2(0.00)
        assert float(metrics["shipped_exposure_rate_per_1000"]) == approx2(0.00)
        assert float(metrics["trigger_threshold"]) == approx2(8.00)
        assert metrics["trigger_breached"] is False
        part = read_part(api, plant.part_id)
        assert part["field_failure_count"] == 0
        assert part["lifecycle_status"] == PartLifecycleStatus.ACTIVE.value
