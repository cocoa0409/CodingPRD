"""Values sitting exactly on a documented boundary, and their neighbours.

An efficiency index that rounds onto 1.00, a bill-of-materials line whose
effective sequence index is inclusive, and a supplier score that lands on the
approved minimum are each checked on the boundary and one step past it.
"""

from test_helpers import (
    ENGINEERING_LEAD_HEADERS,
    PLANT_ADMIN_HEADERS,
    PRODUCTION_PLANNER_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
    ApiErrorId,
    BomLineStatus,
    BuildSlotStatus,
    CertificationTier,
    DeliveryCallStatus,
    QualityStatus,
    SupplierStatus,
    approx2,
    base_plant,
    base_plant_with_shift,
    gated_unit,
    missed_calls_plant,
    module_plant,
    new_bom_line,
    new_delivery_call,
    new_part,
    new_shift_plan,
    planned_slot,
    read_call,
    read_line,
    read_slot,
    read_station,
    read_supplier,
    read_unit,
    run_checkpoint,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    variant_version,
)


class TestEfficiencyIndexAtTheTierCeiling:
    """The certifiable ceiling is inclusive on the two-decimal index."""

    def test_a_weighted_sum_of_zero_point_nine_nine_eight_certifies_as_tier_b(self, api):
        """0.998 rounds onto 1.00, which is still certifiable.

        "The tier is then read off the two-decimal index: an index of at most 0.80
        is `A_PLUS`, at most 0.95 is `A`, and at most 1.00 is `B`. An index above
        1.00 is not certifiable at all."

        Design: Difficulty/boundary_precision_check/efficiency_index_exactly_at_tier_b_maximum_certifies
        """
        plant = base_plant_with_shift(api)
        unit = gated_unit(api, plant, 1, energy=[420.00], water=[184.00])

        certified = validate_success(
            api.certify_unit(unit["id"], QUALITY_INSPECTOR_HEADERS)
        )

        assert float(certified["efficiency_index"]) == approx2(1.00)
        assert certified["certification_tier"] == CertificationTier.B.value
        assert certified["quality_status"] == QualityStatus.CERTIFIED.value

    def test_a_weighted_sum_of_one_point_zero_zero_six_is_refused_and_writes_nothing(self, api):
        """1.006 rounds to 1.01, one hundredth outside the ceiling.

        "Finally, the certification-variant index must be at most 1.00; an index
        above that is refused with `ERR_EFFICIENCY_LIMIT_EXCEEDED` and **nothing**
        is written, neither `efficiency_index` nor `certification_tier` nor the
        status."

        Design: Difficulty/boundary_precision_check/efficiency_index_exactly_at_tier_b_maximum_certifies
        """
        plant = base_plant_with_shift(api)
        unit = gated_unit(api, plant, 1, energy=[420.00], water=[188.00])

        validate_error(
            api.certify_unit(unit["id"], QUALITY_INSPECTOR_HEADERS),
            ApiErrorId.ERR_EFFICIENCY_LIMIT_EXCEEDED,
            expected_status=422,
        )

        after = read_unit(api, unit["id"])
        assert after["quality_status"] == QualityStatus.GATED.value
        assert after["efficiency_index"] is None
        assert after["certification_tier"] is None
        assert float(after["provisional_efficiency_index"]) == approx2(1.01)


class TestEffectiveFromSequenceBoundary:
    """A line effective from index 5 governs 5 and leaves 4 to its predecessor."""

    def _plant_with_two_effective_windows(self, api):
        """Two ACTIVE POS-DOOR lines, one from index 1 and one from index 5.

        The second names a different part at a different station, so which of the
        two governs a slot is visible in two separate presentation counters.
        """
        plant = base_plant(api)
        plant.parts["P-DOOR-B"] = new_part(
            api, plant.supplier_id, "P-DOOR-B",
            is_sequenced_module=False, line_side_max_units=20,
        )
        plant.bom_lines[("WM-X", "POS-DOOR-FROM-5")] = new_bom_line(
            api, plant.variant_id, plant.parts["P-DOOR-B"]["id"], plant.st20_id,
            variant_version(api, plant.variant_id), "POS-DOOR",
            headers=ENGINEERING_LEAD_HEADERS,
            qty_per_unit=3, effective_from_sequence=5,
        )
        plant.shift_plan = new_shift_plan(api, plant.line_id)
        planned_slot(api, plant, 4, "2026-08-03T07:00:00Z")
        planned_slot(api, plant, 5, "2026-08-03T07:30:00Z")
        return plant

    def test_index_four_is_still_governed_by_the_earlier_line(self, api):
        """Slot 4 charges two units at the first station and none at the second.

        "The boundary is inclusive: a line minted with an `effective_from_sequence`
        of 5 does not govern a slot at `sequence_index` 4 — there the earlier line
        still wins — and does govern a slot at `sequence_index` 5."

        Design: Difficulty/boundary_precision_check/bom_effective_from_sequence_inclusive_at_cut_in_index
        """
        plant = self._plant_with_two_effective_windows(api)

        slot = validate_success(
            api.sequence_build_slot(plant.slot_id(4), PRODUCTION_PLANNER_HEADERS)
        )

        assert slot["allocated_slot_units"] == 2
        charges = {a["station_id"]: a["slot_units"] for a in slot["presentation_allocations"]}
        assert charges == {plant.st10_id: 2}
        assert read_station(api, plant.st10_id)["presentation_slots_used"] == 2
        assert read_station(api, plant.st20_id)["presentation_slots_used"] == 0

    def test_index_five_is_governed_by_the_later_line_and_neither_is_superseded(self, api):
        """Slot 5 charges three units at the other station instead.

        "Within each `bom_position_code`, the winner is the candidate with the
        greatest `effective_from_sequence`; ties are broken by `created_at`
        descending and then by `id` descending."

        Design: Difficulty/boundary_precision_check/bom_effective_from_sequence_inclusive_at_cut_in_index
        """
        plant = self._plant_with_two_effective_windows(api)
        validate_success(
            api.sequence_build_slot(plant.slot_id(4), PRODUCTION_PLANNER_HEADERS)
        )

        slot = validate_success(
            api.sequence_build_slot(plant.slot_id(5), PRODUCTION_PLANNER_HEADERS)
        )

        assert slot["allocated_slot_units"] == 3
        charges = {a["station_id"]: a["slot_units"] for a in slot["presentation_allocations"]}
        assert charges == {plant.st20_id: 3}
        assert read_station(api, plant.st20_id)["presentation_slots_used"] == 3
        rows, meta = validate_paginated(
            api.list_bom_lines(PLANT_ADMIN_HEADERS,
                               {"model_variant_id": plant.variant_id})
        )
        assert meta["total_count"] == 2
        assert all(row["status"] == BomLineStatus.ACTIVE.value for row in rows)
        assert all(row["superseded_by_bom_line_id"] is None for row in rows)
        line = read_line(api, plant.line_id)
        assert line["presentation_slots_committed"] == 5
        assert float(line["free_slot_pct"]) == approx2(93.75)


class TestSupplierScoreAtTheApprovedMinimum:
    """Sixty points is inside the approved band; forty is not."""

    def _two_overdue_windows_and_a_future_one(self, api):
        plant = module_plant(api)
        missed_calls_plant(api, plant, [
            ("2026-08-03T06:00:00Z", "2026-08-03T06:30:00Z"),
            ("2026-08-03T06:40:00Z", "2026-08-03T07:10:00Z"),
        ])
        future = new_delivery_call(
            api, plant.supplier_id, plant.part_id, plant.st10_id,
            "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z", sequenced_qty=1,
        )
        planned_slot(api, plant, 1, "2026-08-03T09:30:00Z")
        set_clock(api, "2026-08-03T07:26:00Z")
        return plant, future

    def test_exactly_sixty_points_stays_approved_and_keeps_supplying(self, api):
        """Two misses leave the supplier on the band edge, still usable.

        "The boundary is worth spelling out: two missed calls bring a fresh
        supplier to exactly 60.00, which is still `APPROVED`, and no cancellation
        cascade fires; a third miss brings it to 40.00, which is `PROBATION`, and
        the cascade does fire."

        Design: Difficulty/boundary_precision_check/supplier_score_exactly_at_approved_minimum_stays_approved
        """
        plant, future = self._two_overdue_windows_and_a_future_one(api)

        report = validate_success(
            api.run_checkpoint(plant.line_id, PRODUCTION_PLANNER_HEADERS)
        )

        supplier = read_supplier(api, plant.supplier_id)
        assert supplier["missed_count"] == 2
        assert float(supplier["on_time_score"]) == approx2(60.00)
        assert supplier["status"] == SupplierStatus.APPROVED.value
        assert report["cancelled_call_ids"] == []
        assert report["demoted_supplier_ids"] == []
        assert read_call(api, future["id"])["status"] == DeliveryCallStatus.SCHEDULED.value
        # Validation 27 admits a supplier sitting exactly on the minimum.
        slot = validate_success(
            api.sequence_build_slot(plant.slot_id(1), PRODUCTION_PLANNER_HEADERS)
        )
        assert slot["status"] == BuildSlotStatus.SEQUENCED.value
        assert slot["sync_delivery_call_id"] == future["id"]
        assert slot["allocated_slot_units"] == 0

    def test_the_third_miss_drops_the_band_but_a_missed_call_de_sequences_nothing(self, api):
        """Forty points is PROBATION, yet the slot keeps its booking.

        "The supplier's `status` is then re-derived from the clamped score: at least
        60.00 is `APPROVED`, at least 40.00 is `PROBATION`, and anything below that
        is `SUSPENDED`."

        Design: Difficulty/boundary_precision_check/supplier_score_exactly_at_approved_minimum_stays_approved
        """
        plant, future = self._two_overdue_windows_and_a_future_one(api)
        run_checkpoint(api, plant.line_id)
        validate_success(
            api.sequence_build_slot(plant.slot_id(1), PRODUCTION_PLANNER_HEADERS)
        )
        set_clock(api, "2026-08-03T10:16:00Z")

        validate_success(api.run_checkpoint(plant.line_id, PRODUCTION_PLANNER_HEADERS))

        supplier = read_supplier(api, plant.supplier_id)
        assert supplier["missed_count"] == 3
        assert float(supplier["on_time_score"]) == approx2(40.00)
        assert supplier["status"] == SupplierStatus.PROBATION.value
        assert read_call(api, future["id"])["status"] == DeliveryCallStatus.MISSED.value
        assert read_slot(api, plant.slot_id(1))["status"] == BuildSlotStatus.SEQUENCED.value
