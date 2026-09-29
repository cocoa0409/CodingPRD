"""Transitions whose whole point is the side effect they do or do not fire.

Cancelling a call only unwinds slots that actually pinned it; a stop blocks the
children of the line and a restart releases them; a changeover retools the line
and books minutes; and the no-fault warranty branch charges nobody.
"""

from test_helpers import (
    ENGINEERING_LEAD_HEADERS,
    LINE_OPERATOR_HEADERS,
    PRODUCTION_PLANNER_HEADERS,
    WARRANTY_ANALYST_HEADERS,
    ApiErrorId,
    BuildSlotStatus,
    CancelReason,
    DeliveryCallStatus,
    Disposition,
    LineOperatingMode,
    LinePosture,
    PartLifecycleStatus,
    SupplierStatus,
    WarrantyReturnStatus,
    analyze_payload,
    approx2,
    assert_pristine_slot,
    base_plant_with_shift,
    cancel_call,
    module_plant,
    new_delivery_call,
    planned_slot,
    read_line,
    read_part,
    read_return,
    read_shift_plan,
    read_slot,
    read_station,
    read_supplier,
    same_instant,
    sequence_slot,
    set_clock,
    shipped_unit,
    start_line,
    stop_line,
    torn_down_return,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCancellationCascadeIsConditional:
    """The reversal fires on pinned slots only, and a PLANNED slot pinned nothing."""

    def test_cancelling_a_call_no_slot_ever_pinned_unwinds_nothing(self, api):
        """A slot that was never sequenced is outside the cascade.

        "That takes it `SCHEDULED → CANCELLED` with `cancel_reason` `PLANNER`, and
        every build slot whose pinned call it was and which is still `SEQUENCED` is
        un-sequenced to `PLANNED`, replaying the full reversal: presentation slots
        released, shift labour recomputed and line posture re-derived."

        "The slot arrives with `status` `PLANNED`, and at that moment it consumes
        nothing: `shift_plan_id`, `sync_delivery_call_id`, `option_points_snapshot` and
        `labor_minutes_snapshot` are all null, `presentation_allocations` is empty and
        `allocated_slot_units` is 0."

        Design: Corner/state_machines/cancelling_a_call_whose_slot_is_only_planned_cascades_nothing
        """
        plant = module_plant(api)
        call = new_delivery_call(
            api, plant.supplier_id, plant.parts["P-MOD-1"]["id"], plant.st10_id,
            "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z", sequenced_qty=1,
        )
        planned_slot(api, plant, 1, "2026-08-03T09:30:00Z")

        cancelled = cancel_call(api, call["id"])

        assert cancelled["status"] == DeliveryCallStatus.CANCELLED.value
        assert cancelled["cancel_reason"] == CancelReason.PLANNER.value
        assert_pristine_slot(read_slot(api, plant.slot_id(1)))
        assert read_shift_plan(api, plant.shift_plan_id)["committed_labor_minutes"] == 0
        assert read_station(api, plant.st10_id)["presentation_slots_used"] == 0
        line = read_line(api, plant.line_id)
        assert line["posture"] == LinePosture.OPEN.value
        assert float(line["free_slot_pct"]) == approx2(100.00)


class TestStoppingAndRestartingTheLine:
    """A stop reaches every child operation; a start hands them back."""

    def test_sequencing_is_blocked_while_stopped_and_succeeds_once_restarted(self, api):
        """The identical request fails and then succeeds, decided by posture alone.

        "While the line is stopped, sequencing and releasing build slots are both
        refused with `ERR_LINE_POSTURE_BLOCKED` — and, as §3.8 explains, a stopped line
        is exactly the condition an engineering change needs in order to be cut in."

        Design: Corner/state_machines/stopping_the_line_blocks_sequencing_until_it_is_restarted
        """
        plant = base_plant_with_shift(api)
        planned_slot(api, plant, 1, "2026-08-03T07:00:00Z")
        stop_line(api, plant.line_id, "tooling inspection")

        validate_error(
            api.sequence_build_slot(plant.slot_id(1), PRODUCTION_PLANNER_HEADERS),
            ApiErrorId.ERR_LINE_POSTURE_BLOCKED,
            expected_status=409,
        )

        stopped = read_line(api, plant.line_id)
        assert stopped["operating_mode"] == LineOperatingMode.STOPPED.value
        assert stopped["stop_reason"] == "tooling inspection"
        assert stopped["posture"] == LinePosture.STOPPED.value

        restarted = start_line(api, plant.line_id)

        assert restarted["operating_mode"] == LineOperatingMode.RUNNING.value
        assert restarted["stop_reason"] is None
        assert restarted["changeover_count"] == 0
        assert restarted["posture"] == LinePosture.OPEN.value

        sequenced = validate_success(
            api.sequence_build_slot(plant.slot_id(1), PRODUCTION_PLANNER_HEADERS)
        )

        assert sequenced["status"] == BuildSlotStatus.SEQUENCED.value
        assert sequenced["allocated_slot_units"] == 2
        assert read_shift_plan(api, plant.shift_plan_id)["committed_labor_minutes"] == 150

    def test_a_changeover_restart_retools_the_line_and_books_eighteen_minutes(self, api):
        """Retooling to another family charges the covering plan before any slot does.

        "When `to_family_code` is supplied **and differs** from the line's
        `current_family_code`, three things happen together: `current_family_code` is
        replaced by the supplied value, `changeover_count` is incremented by one, and
        eighteen changeover minutes are added to the `changeover_minutes` of the line's
        active shift plan whose window contains the logical clock, which in turn
        re-derives that plan's `committed_labor_minutes`."

        Design: Corner/state_machines/changeover_start_books_eighteen_minutes_and_retools_the_line
        """
        plant = base_plant_with_shift(api)
        planned_slot(api, plant, 1, "2026-08-03T07:00:00Z")
        stop_line(api, plant.line_id, "model changeover")

        retooled = start_line(api, plant.line_id, to_family_code="FAM_B")

        assert retooled["current_family_code"] == "FAM_B"
        assert retooled["changeover_count"] == 1
        assert retooled["operating_mode"] == LineOperatingMode.RUNNING.value
        assert retooled["posture"] == LinePosture.OPEN.value
        booked = read_shift_plan(api, plant.shift_plan_id)
        assert booked["unit_labor_minutes"] == 0
        assert booked["changeover_minutes"] == 18
        assert booked["committed_labor_minutes"] == 18

        sequenced = sequence_slot(api, plant.slot_id(1))

        assert sequenced["status"] == BuildSlotStatus.SEQUENCED.value
        charged = read_shift_plan(api, plant.shift_plan_id)
        assert charged["unit_labor_minutes"] == 150
        # The start's eighteen minutes plus one FAM_A-against-FAM_B boundary.
        assert charged["changeover_minutes"] == 36
        assert charged["committed_labor_minutes"] == 186

        validate_error(
            api.release_build_slot(plant.slot_id(1), LINE_OPERATOR_HEADERS),
            ApiErrorId.ERR_CHANGEOVER_REQUIRED,
            expected_status=409,
        )

        assert read_slot(api, plant.slot_id(1))["status"] == \
            BuildSlotStatus.SEQUENCED.value
        _rows, meta = validate_paginated(
            api.list_production_units(PRODUCTION_PLANNER_HEADERS,
                                      {"build_slot_id": plant.slot_id(1)})
        )
        assert meta["total_count"] == 0


class TestNoFaultFoundBranch:
    """The one analysis branch that closes the return and charges nobody."""

    def test_a_no_fault_analysis_closes_the_return_and_moves_no_counter(self, api):
        """One step from teardown to closed, with every ledger untouched.

        "A `disposition` of `NO_FAULT_FOUND` requires that no `root_cause_part_id` be
        supplied and takes the return straight `TEARDOWN → CLOSED`. No counter moves,
        no change is minted, and the return needs no separate closure."

        Design: Corner/state_machines/no_fault_found_disposition_closes_the_return_without_charging_anyone
        """
        plant = base_plant_with_shift(api)
        unit = shipped_unit(api, plant, 1)
        set_clock(api, "2026-08-03T12:00:00Z")
        wr = torn_down_return(api, plant, unit["id"], field_hours=500,
                              returned_at="2026-08-03T11:00:00Z")
        assert wr["status"] == WarrantyReturnStatus.TEARDOWN.value

        closed = validate_success(
            api.analyze_warranty_return(
                wr["id"], analyze_payload(Disposition.NO_FAULT_FOUND.value),
                WARRANTY_ANALYST_HEADERS,
            )
        )

        assert closed["status"] == WarrantyReturnStatus.CLOSED.value
        assert closed["disposition"] == Disposition.NO_FAULT_FOUND.value
        assert closed["root_cause_part_id"] is None
        assert closed["engineering_change_id"] is None
        assert same_instant(closed["teardown_started_at"], "2026-08-03T12:00:00Z")
        part = read_part(api, plant.part_id)
        assert part["field_failure_count"] == 0
        assert float(part["cohort_failure_rate_per_1000"]) == approx2(0.00)
        assert part["lifecycle_status"] == PartLifecycleStatus.ACTIVE.value
        supplier = read_supplier(api, plant.supplier_id)
        assert supplier["quality_penalty_count"] == 0
        assert float(supplier["on_time_score"]) == approx2(100.00)
        assert supplier["status"] == SupplierStatus.APPROVED.value
        _rows, meta = validate_paginated(
            api.list_engineering_changes(
                ENGINEERING_LEAD_HEADERS, {"source_warranty_return_id": wr["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert read_return(api, wr["id"])["status"] == WarrantyReturnStatus.CLOSED.value
