"""Single requests whose effects travel three and four links down the plant.

An overdue checkpoint reaches from a delivery window to a build slot's labour
booking; a cut-in reaches from a bill-of-materials position to the presentation
slots a station had already charged; and a field failure reaches from a counter
recomputation to the refusal of the next sequencing attempt.
"""

from test_helpers import (
    ENGINEERING_LEAD_HEADERS,
    PLANT_ADMIN_HEADERS,
    PRODUCTION_PLANNER_HEADERS,
    WARRANTY_ANALYST_HEADERS,
    ApiErrorId,
    BomLineStatus,
    BuildSlotStatus,
    CancelReason,
    ChangeOrigin,
    DeliveryCallStatus,
    Disposition,
    EngineeringChangeStatus,
    LinePosture,
    PartLifecycleStatus,
    SupplierStatus,
    WarrantyReturnStatus,
    analyze_payload,
    approx2,
    base_plant_with_shift,
    cut_in_ready_plant,
    make_engineering_lead_headers,
    missed_calls_plant,
    module_plant,
    new_delivery_call,
    planned_slot,
    read_call,
    read_line,
    read_part,
    read_shift_plan,
    read_slot,
    read_station,
    read_supplier,
    run_checkpoint,
    same_instant,
    sequenced_slot,
    set_clock,
    shipped_unit,
    torn_down_return,
    validate_error,
    validate_paginated,
    validate_success,
)


def _line_with_two_misses_already_swept(api):
    """A supplier already down to 60.00, one overdue call and one covering call.

    The first sweep at 07:26 takes the two early windows; the third window is
    left overdue for the sweep under test, and the 09:00 window is what makes
    build slot 1 sequenceable in the first place.
    """
    plant = module_plant(api)
    missed_calls_plant(api, plant, [
        ("2026-08-03T06:00:00Z", "2026-08-03T06:30:00Z"),
        ("2026-08-03T06:40:00Z", "2026-08-03T07:10:00Z"),
    ])
    set_clock(api, "2026-08-03T07:26:00Z")
    run_checkpoint(api, plant.line_id)
    overdue = new_delivery_call(
        api, plant.supplier_id, plant.part_id, plant.st10_id,
        "2026-08-03T07:30:00Z", "2026-08-03T08:00:00Z", sequenced_qty=1,
    )
    covering = new_delivery_call(
        api, plant.supplier_id, plant.part_id, plant.st10_id,
        "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z", sequenced_qty=1,
    )
    sequenced_slot(api, plant, 1, "2026-08-03T09:30:00Z")
    set_clock(api, "2026-08-03T08:16:00Z")
    return plant, overdue, covering


class TestCheckpointMissCascade:
    """One overdue window costs the supplier its band and the slot its booking."""

    def test_the_overdue_window_is_swept_and_the_supplier_is_demoted(self, api):
        """The third miss takes the score to 40.00 and the band to PROBATION.

        "Each one increments its supplier's `missed_count` and subtracts 20 points
        from its `on_time_score` with a floor of 0.00, then re-derives the
        supplier's `status`; a supplier demoted out of `APPROVED` has every one of
        its remaining `SCHEDULED` calls not already swept in this checkpoint
        cancelled with `cancel_reason` `SUPPLIER_PROBATION`, and every build slot
        pinned to one of those cancellations and still `SEQUENCED` is un-sequenced
        to `PLANNED` with the full reversal."

        Design: Difficulty/transitive_cascade/checkpoint_miss_demotes_supplier_and_de_sequences_slot_depth_four
        """
        plant, overdue, _covering = _line_with_two_misses_already_swept(api)

        report = validate_success(
            api.run_checkpoint(plant.line_id, PRODUCTION_PLANNER_HEADERS)
        )

        assert report["missed_call_ids"] == [overdue["id"]]
        assert report["demoted_supplier_ids"] == [plant.supplier_id]
        assert report["checkpoint_index"] == 2
        supplier = read_supplier(api, plant.supplier_id)
        assert supplier["missed_count"] == 3
        assert float(supplier["on_time_score"]) == approx2(40.00)
        assert supplier["status"] == SupplierStatus.PROBATION.value

    def test_the_demotion_cancels_the_covering_call_and_frees_the_slot(self, api):
        """Links three and four: the pinned call dies and the slot un-books.

        "The identical `SEQUENCED → PLANNED` reversal runs automatically, with no
        operator involved, whenever the slot's pinned `sync_delivery_call_id` is
        cancelled for any reason at all — planner cancellation, supplier demotion
        or a part going service-only."

        Design: Difficulty/transitive_cascade/checkpoint_miss_demotes_supplier_and_de_sequences_slot_depth_four
        """
        plant, _overdue, covering = _line_with_two_misses_already_swept(api)
        slot_id = plant.slot_id(1)

        report = validate_success(
            api.run_checkpoint(plant.line_id, PRODUCTION_PLANNER_HEADERS)
        )

        assert report["cancelled_call_ids"] == [covering["id"]]
        assert report["de_sequenced_build_slot_ids"] == [slot_id]
        cancelled = read_call(api, covering["id"])
        assert cancelled["status"] == DeliveryCallStatus.CANCELLED.value
        assert cancelled["cancel_reason"] == CancelReason.SUPPLIER_PROBATION.value
        slot = read_slot(api, slot_id)
        assert slot["status"] == BuildSlotStatus.PLANNED.value
        assert slot["sync_delivery_call_id"] is None
        assert slot["shift_plan_id"] is None
        assert slot["labor_minutes_snapshot"] is None
        assert slot["allocated_slot_units"] == 0
        plan = read_shift_plan(api, plant.shift_plan_id)
        assert plan["unit_labor_minutes"] == 0
        assert plan["committed_labor_minutes"] == 0
        line = read_line(api, plant.line_id)
        assert line["posture"] == LinePosture.OPEN.value
        assert float(line["free_slot_pct"]) == approx2(100.00)


class TestCutInCascade:
    """Superseding a position rewrites four other records in one request."""

    def test_cut_in_supersedes_the_line_and_puts_the_part_into_service_only(self, api):
        """The new line is minted, the old one superseded, the part obligated.

        "A new bill-of-materials line is minted, with its `part_id` set to the
        replacement part, its `station_id` and its `qty_per_unit` inherited from the
        superseded line unless `new_qty_per_unit` was supplied, its
        `effective_from_sequence` set to `cut_in_sequence_index`, its
        `created_by_change_id` set to this change and its `status` `ACTIVE`."

        Design: Difficulty/transitive_cascade/engineering_change_cut_in_supersedes_bom_and_releases_line_side_depth_four
        """
        plant = cut_in_ready_plant(api)
        change = plant.changes[-1]
        old_line_id = plant.bom_lines[("WM-M", "POS-MOD")]["id"]

        cut_in = validate_success(
            api.cut_in_engineering_change(
                change["id"], make_engineering_lead_headers("eng-bob")
            )
        )

        assert cut_in["status"] == EngineeringChangeStatus.CUT_IN.value
        assert same_instant(cut_in["cut_in_at"], "2026-08-03T08:00:00Z")
        minted, meta = validate_paginated(
            api.list_bom_lines(PLANT_ADMIN_HEADERS,
                               {"created_by_change_id": change["id"]})
        )
        assert meta["total_count"] == 1
        assert minted[0]["part_id"] == plant.parts["P-MOD-2"]["id"]
        assert minted[0]["station_id"] == plant.st10_id
        assert minted[0]["qty_per_unit"] == 1
        assert minted[0]["effective_from_sequence"] == 5
        assert minted[0]["status"] == BomLineStatus.ACTIVE.value
        old_line = validate_success(
            api.get_bom_line(old_line_id, PLANT_ADMIN_HEADERS)
        )
        assert old_line["status"] == BomLineStatus.SUPERSEDED.value
        assert old_line["superseded_by_bom_line_id"] == minted[0]["id"]
        outgoing = read_part(api, plant.parts["P-MOD-1"]["id"])
        assert outgoing["lifecycle_status"] == PartLifecycleStatus.SERVICE_ONLY.value
        assert same_instant(outgoing["service_obligation_until"],
                            "2036-08-03T08:00:00Z")

    def test_cut_in_cancels_the_future_call_and_gives_back_line_side_space(self, api):
        """Links three and four, and the obligation then blocks retirement.

        "Every build slot pinned to one of those cancelled calls and still
        `SEQUENCED` is un-sequenced to `PLANNED`, releasing its presentation slots,
        recomputing its shift plan's labour figures and re-deriving the line's
        `posture`."

        Design: Difficulty/transitive_cascade/engineering_change_cut_in_supersedes_bom_and_releases_line_side_depth_four
        """
        plant = cut_in_ready_plant(api)
        change = plant.changes[-1]
        call = plant.calls[-1]
        slot_id = plant.slot_id(1)
        assert read_station(api, plant.st20_id)["presentation_slots_used"] == 2

        validate_success(
            api.cut_in_engineering_change(
                change["id"], make_engineering_lead_headers("eng-bob")
            )
        )

        cancelled = read_call(api, call["id"])
        assert cancelled["status"] == DeliveryCallStatus.CANCELLED.value
        assert cancelled["cancel_reason"] == CancelReason.PART_SERVICE_ONLY.value
        slot = read_slot(api, slot_id)
        assert slot["status"] == BuildSlotStatus.PLANNED.value
        assert slot["sync_delivery_call_id"] is None
        assert slot["allocated_slot_units"] == 0
        assert read_station(api, plant.st20_id)["presentation_slots_used"] == 0
        assert read_station(api, plant.st10_id)["presentation_slots_used"] == 0
        assert read_shift_plan(api, plant.shift_plan_id)["committed_labor_minutes"] == 0
        # The ten-year obligation starts at the cut-in instant, so retiring the
        # part at that same instant is still inside it.
        validate_error(
            api.obsolete_part(plant.parts["P-MOD-1"]["id"], PLANT_ADMIN_HEADERS),
            ApiErrorId.ERR_SERVICE_OBLIGATION_ACTIVE,
        )
        assert read_part(api, plant.parts["P-MOD-1"]["id"])["lifecycle_status"] == \
            PartLifecycleStatus.SERVICE_ONLY.value


class TestWarrantyDesignFeedbackCascade:
    """A recomputed rate mints a change that then blocks the floor."""

    def _shipped_cohort_of_one(self, api):
        plant = base_plant_with_shift(api)
        shipped_unit(api, plant, 1)
        planned_slot(api, plant, 2, "2026-08-03T08:00:00Z")
        set_clock(api, "2026-08-03T12:00:00Z")
        wr = torn_down_return(api, plant, plant.unit_id(1), field_hours=500)
        return plant, wr

    def test_a_breaching_rate_mints_a_warranty_origin_change(self, api):
        """One failure over a cohort of one is 1000.00 and fires the cascade.

        "If that recomputed cohort rate is greater than or equal to 8.00, the
        design-feedback cascade fires: a `WARRANTY`-origin engineering change is
        minted directly in `SUBMITTED`, with its `model_variant_id` and
        `bom_position_code` taken from the unit's as-built bill of materials, its
        `affected_part_id` set to the root-cause part, its `replacement_part_id`
        left null for an engineer to fill in later, its `target_line_id` set to the
        line the unit was built on, its `cut_in_sequence_index` set to that line's
        `max_released_sequence_index` plus one, and its `submitted_by_user_id`
        recorded as the literal value `system`."

        Design: Difficulty/transitive_cascade/warranty_design_defect_mints_change_and_blocks_sequencing_depth_three
        """
        plant, wr = self._shipped_cohort_of_one(api)

        analysed = validate_success(
            api.analyze_warranty_return(
                wr["id"],
                analyze_payload(Disposition.DESIGN_DEFECT.value, plant.part_id),
                WARRANTY_ANALYST_HEADERS,
            )
        )

        part = read_part(api, plant.part_id)
        assert part["field_failure_count"] == 1
        assert float(part["cohort_failure_rate_per_1000"]) == approx2(1000.00)
        minted, meta = validate_paginated(
            api.list_engineering_changes(ENGINEERING_LEAD_HEADERS,
                                         {"source_warranty_return_id": wr["id"]})
        )
        assert meta["total_count"] == 1
        assert minted[0]["origin"] == ChangeOrigin.WARRANTY.value
        assert minted[0]["status"] == EngineeringChangeStatus.SUBMITTED.value
        assert minted[0]["model_variant_id"] == plant.variant_id
        assert minted[0]["bom_position_code"] == "POS-DOOR"
        assert minted[0]["target_line_id"] == plant.line_id
        assert minted[0]["cut_in_sequence_index"] == 2
        assert minted[0]["replacement_part_id"] is None
        assert analysed["status"] == WarrantyReturnStatus.ANALYZED_DESIGN.value
        assert analysed["engineering_change_id"] == minted[0]["id"]

    def test_the_minted_change_blocks_the_next_sequencing_attempt(self, api):
        """The third link: a pending part refuses the waiting slot.

        "Submission also moves the affected part `ACTIVE → CHANGE_PENDING`, and a
        `CHANGE_PENDING` part immediately blocks the sequencing of every variant
        whose effective bill of materials contains it, with
        `ERR_PART_CHANGE_PENDING`."

        Design: Difficulty/transitive_cascade/warranty_design_defect_mints_change_and_blocks_sequencing_depth_three
        """
        plant, wr = self._shipped_cohort_of_one(api)
        validate_success(
            api.analyze_warranty_return(
                wr["id"],
                analyze_payload(Disposition.DESIGN_DEFECT.value, plant.part_id),
                WARRANTY_ANALYST_HEADERS,
            )
        )
        assert read_part(api, plant.part_id)["lifecycle_status"] == \
            PartLifecycleStatus.CHANGE_PENDING.value

        validate_error(
            api.sequence_build_slot(plant.slot_id(2), PRODUCTION_PLANNER_HEADERS),
            ApiErrorId.ERR_PART_CHANGE_PENDING,
        )

        assert read_slot(api, plant.slot_id(2))["status"] == BuildSlotStatus.PLANNED.value
