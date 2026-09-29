"""Ledgers that must come back to exactly where they started.

Sequencing charges presentation slots and labour minutes, and un-sequencing has
to refund precisely the recorded amounts; analysing a warranty return charges a
part and its supplier, and withdrawing the return has to refund those too.
"""

from test_helpers import (
    ENGINEERING_LEAD_HEADERS,
    PRODUCTION_PLANNER_HEADERS,
    WARRANTY_ANALYST_HEADERS,
    AssemblyStatus,
    BuildSlotStatus,
    Disposition,
    LinePosture,
    PartLifecycleStatus,
    SupplierStatus,
    WarrantyReturnStatus,
    approx2,
    base_plant_with_shift,
    de_sequence_slot,
    planned_slot,
    read_line,
    read_part,
    read_shift_plan,
    read_slot,
    read_station,
    read_supplier,
    read_unit,
    sequence_slot,
    set_clock,
    shipped_unit,
    supplier_defect_return,
    validate_paginated,
    validate_success,
)


class TestPresentationSlotAndLabourLedger:
    """Two units of dock space and 150 minutes, charged and refunded."""

    def _plant_with_one_planned_slot(self, api):
        plant = base_plant_with_shift(api)
        planned_slot(api, plant, 1, "2026-08-03T07:00:00Z")
        return plant

    def test_sequencing_charges_the_station_the_line_and_the_shift_plan(self, api):
        """One request writes the snapshots and moves three ledgers.

        "`presentation_allocations` records one object per charged station, each
        carrying that `station_id` and its `slot_units`, and `allocated_slot_units`
        records their sum. Each station's `presentation_slots_used` is then increased
        by its charge in ascending `position_index` order, the line's
        `presentation_slots_committed`, `free_slot_pct` and `posture` are re-derived,
        and the covering plan's `unit_labor_minutes`, `changeover_minutes` and
        `committed_labor_minutes` are recomputed."

        Design: Difficulty/compensating_invariant/presentation_slot_units_and_shift_labour_conserved_across_de_sequence
        """
        plant = self._plant_with_one_planned_slot(api)

        slot = validate_success(
            api.sequence_build_slot(plant.slot_id(1), PRODUCTION_PLANNER_HEADERS)
        )

        assert slot["allocated_slot_units"] == 2
        assert slot["option_points_snapshot"] == 4
        assert slot["labor_minutes_snapshot"] == 150
        assert slot["shift_plan_id"] == plant.shift_plan_id
        assert read_station(api, plant.st10_id)["presentation_slots_used"] == 2
        assert read_station(api, plant.st20_id)["presentation_slots_used"] == 0
        line = read_line(api, plant.line_id)
        assert line["presentation_slots_committed"] == 2
        assert float(line["free_slot_pct"]) == approx2(97.50)
        plan = read_shift_plan(api, plant.shift_plan_id)
        assert plan["unit_labor_minutes"] == 150
        assert plan["changeover_minutes"] == 0
        assert plan["committed_labor_minutes"] == 150

    def test_un_sequencing_refunds_every_charge_and_re_sequencing_does_not_drift(self, api):
        """The refund is the recorded amount, and the recharge is identical.

        "Whatever per-station `slot_units` a build slot charged at sequencing time is
        recorded on that slot, and un-sequencing gives back exactly those recorded
        amounts to exactly those stations — never a recomputed figure."

        Design: Difficulty/compensating_invariant/presentation_slot_units_and_shift_labour_conserved_across_de_sequence
        """
        plant = self._plant_with_one_planned_slot(api)
        sequence_slot(api, plant.slot_id(1))

        de_sequence_slot(api, plant.slot_id(1))

        assert read_station(api, plant.st10_id)["presentation_slots_used"] == 0
        line = read_line(api, plant.line_id)
        assert line["presentation_slots_committed"] == 0
        assert float(line["free_slot_pct"]) == approx2(100.00)
        assert line["posture"] == LinePosture.OPEN.value
        plan = read_shift_plan(api, plant.shift_plan_id)
        assert plan["unit_labor_minutes"] == 0
        assert plan["committed_labor_minutes"] == 0
        emptied = read_slot(api, plant.slot_id(1))
        assert emptied["status"] == BuildSlotStatus.PLANNED.value
        assert emptied["shift_plan_id"] is None
        assert emptied["sync_delivery_call_id"] is None
        assert emptied["option_points_snapshot"] is None
        assert emptied["labor_minutes_snapshot"] is None
        assert emptied["presentation_allocations"] == []
        assert emptied["allocated_slot_units"] == 0

        recharged = sequence_slot(api, plant.slot_id(1))

        assert recharged["allocated_slot_units"] == 2
        assert read_station(api, plant.st10_id)["presentation_slots_used"] == 2
        line_again = read_line(api, plant.line_id)
        assert line_again["presentation_slots_committed"] == 2
        assert float(line_again["free_slot_pct"]) == approx2(97.50)
        assert read_shift_plan(api, plant.shift_plan_id)["committed_labor_minutes"] == 150


class TestDefectAttributionLedger:
    """A supplier-defect charge and its full refund on withdrawal."""

    def _supplier_charged_for_one_field_failure(self, api):
        plant = base_plant_with_shift(api)
        shipped_unit(api, plant, 1)
        set_clock(api, "2026-08-03T12:00:00Z")
        wr = supplier_defect_return(api, plant, plant.unit_id(1), field_hours=500)
        return plant, wr

    def test_withdrawal_rewrites_the_disposition_and_gives_the_part_back(self, api):
        """The failure leaves the numerator but the root cause stays on file.

        "Its `disposition` is rewritten to `NO_FAULT_FOUND` while
        `root_cause_part_id` is deliberately kept for audit. The charged part's
        `field_failure_count` is decremented by one and its
        `cohort_failure_rate_per_1000` recomputed."

        Design: Difficulty/compensating_invariant/defect_attribution_conserved_across_warranty_withdrawal
        """
        plant, wr = self._supplier_charged_for_one_field_failure(api)
        charged = read_part(api, plant.part_id)
        assert charged["field_failure_count"] == 1
        assert float(charged["cohort_failure_rate_per_1000"]) == approx2(1000.00)

        withdrawn = validate_success(
            api.withdraw_warranty_return(wr["id"], WARRANTY_ANALYST_HEADERS)
        )

        assert withdrawn["status"] == WarrantyReturnStatus.CLOSED.value
        assert withdrawn["disposition"] == Disposition.NO_FAULT_FOUND.value
        assert withdrawn["root_cause_part_id"] == plant.part_id
        refunded = read_part(api, plant.part_id)
        assert refunded["field_failure_count"] == 0
        assert float(refunded["cohort_failure_rate_per_1000"]) == approx2(0.00)
        assert refunded["lifecycle_status"] == PartLifecycleStatus.ACTIVE.value

    def test_withdrawal_refunds_the_supplier_quality_charge_in_full(self, api):
        """Ten points come back and the penalty counter returns to zero.

        "When the return had been attributed to a supplier, that supplier's
        `quality_penalty_count` is decremented by one, 10 points are added back to
        its `on_time_score` capped at 100.00, and its `status` is re-derived."

        Design: Difficulty/compensating_invariant/defect_attribution_conserved_across_warranty_withdrawal
        """
        plant, wr = self._supplier_charged_for_one_field_failure(api)
        charged = read_supplier(api, plant.supplier_id)
        assert charged["quality_penalty_count"] == 1
        assert float(charged["on_time_score"]) == approx2(90.00)

        validate_success(
            api.withdraw_warranty_return(wr["id"], WARRANTY_ANALYST_HEADERS)
        )

        supplier = read_supplier(api, plant.supplier_id)
        assert supplier["quality_penalty_count"] == 0
        assert float(supplier["on_time_score"]) == approx2(100.00)
        assert supplier["status"] == SupplierStatus.APPROVED.value
        # The supplier branch minted nothing, so there is nothing to cancel.
        _rows, meta = validate_paginated(
            api.list_engineering_changes(ENGINEERING_LEAD_HEADERS,
                                         {"source_warranty_return_id": wr["id"]})
        )
        assert meta["total_count"] == 0
        assert read_unit(api, plant.unit_id(1))["assembly_status"] == \
            AssemblyStatus.SHIPPED.value
