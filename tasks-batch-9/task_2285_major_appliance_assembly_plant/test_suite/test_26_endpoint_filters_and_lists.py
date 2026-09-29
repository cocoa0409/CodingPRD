"""What the collections answer when they are asked a narrow question.

The bill-of-materials list can resolve the set that governs one sequence index;
parent-scoped lists never leak across their parent; the warranty close files a
note without moving a counter; and every other filter composes with the rest.
"""

from test_helpers import (
    ENGINEERING_LEAD_HEADERS,
    PLANT_ADMIN_HEADERS,
    PRODUCTION_PLANNER_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
    WARRANTY_ANALYST_HEADERS,
    ApiErrorId,
    AssemblyStatus,
    BomLineStatus,
    CancelReason,
    CertificationTier,
    ChangeOrigin,
    DeliveryCallStatus,
    Disposition,
    EngineeringChangeStatus,
    PartLifecycleStatus,
    QualityStatus,
    QualityTestStatus,
    SupplierStatus,
    TestResult,
    TestType,
    WarrantyReturnStatus,
    approx2,
    base_plant,
    base_plant_with_shift,
    cancel_call,
    close_return_payload,
    make_engineering_lead_headers,
    new_bom_line,
    new_delivery_call,
    new_line,
    read_part,
    read_return,
    read_supplier,
    set_clock,
    shipped_unit,
    submitted_change,
    supplier_defect_return,
    validate_error,
    validate_paginated,
    validate_success,
    variant_version,
)


class TestEffectiveBomResolution:
    """Two lines share a position; the queried index decides which one governs."""

    def test_index_four_still_draws_the_old_line_and_index_five_draws_the_new_one(
            self, api):
        """The same position, resolved on either side of the cut.

        "Bill-of-materials lines can be listed and filtered by `model_variant_id`,
        `part_id`, `station_id`, `superseded_by_bom_line_id`, `created_by_change_id`,
        `bom_position_code` and `status`, and by `effective_at_sequence`, which applies
        the resolution above at the supplied index — the production-effective flavour
        when `status` is omitted or given as `ACTIVE`, and the as-built flavour when
        superseded lines are requested through `status` equal to `SUPERSEDED`."

        "The boundary is inclusive: a line minted with an `effective_from_sequence` of 5
        does not govern a slot at `sequence_index` 4 — there the earlier line still wins
        — and does govern a slot at `sequence_index` 5."

        Design: Corner/endpoints/bom_line_list_resolves_the_effective_set_at_a_sequence_index
        """
        plant = base_plant(api)
        original = plant.bom_lines[("WM-X", "POS-DOOR")]

        later = new_bom_line(
            api, plant.variant_id, plant.part_id, plant.st10_id,
            variant_version(api, plant.variant_id), "POS-DOOR",
            qty_per_unit=3, effective_from_sequence=5,
        )

        assert later["status"] == BomLineStatus.ACTIVE.value
        assert later["effective_from_sequence"] == 5

        before_the_cut, before_meta = validate_paginated(
            api.list_bom_lines(ENGINEERING_LEAD_HEADERS,
                               {"model_variant_id": plant.variant_id,
                                "effective_at_sequence": 4})
        )

        assert before_meta["total_count"] == 1
        assert before_the_cut[0]["id"] == original["id"]
        assert before_the_cut[0]["qty_per_unit"] == 2

        at_the_cut, at_meta = validate_paginated(
            api.list_bom_lines(ENGINEERING_LEAD_HEADERS,
                               {"model_variant_id": plant.variant_id,
                                "effective_at_sequence": 5})
        )

        assert at_meta["total_count"] == 1
        assert at_the_cut[0]["id"] == later["id"]
        assert at_the_cut[0]["qty_per_unit"] == 3

        # Without an index, both lines are simply active lines of the variant.
        unresolved, unresolved_meta = validate_paginated(
            api.list_bom_lines(ENGINEERING_LEAD_HEADERS,
                               {"model_variant_id": plant.variant_id,
                                "status": BomLineStatus.ACTIVE.value})
        )

        assert unresolved_meta["total_count"] == 2
        assert unresolved_meta["has_more"] is False
        assert {row["id"] for row in unresolved} == {original["id"], later["id"]}
        untouched = validate_success(
            api.get_bom_line(original["id"], ENGINEERING_LEAD_HEADERS)
        )
        assert untouched["status"] == BomLineStatus.ACTIVE.value
        assert untouched["superseded_by_bom_line_id"] is None


class TestParentScopedLists:
    """A child list is a window onto one parent and nothing else."""

    def test_the_stations_of_one_line_paginate_without_seeing_another_line(self, api):
        """Two pages of one line's stations, and an empty page for the other line.

        "Every list response repeats `limit` and `offset` in the `meta` object alongside
        `total_count` (the number of records matching the filters before pagination) and
        `has_more` (true when records remain beyond the current page)."

        "Plans of a line can be listed and filtered by `shift_date`, `shift_code` and
        `status`, and a single-plan read exposes `unit_labor_minutes`,
        `changeover_minutes`, `committed_labor_minutes` and `available_labor_minutes`
        together."

        Design: Corner/endpoints/parent_scoped_lists_paginate_within_their_own_line
        """
        plant = base_plant_with_shift(api)
        other = new_line(api, "L2", takt_seconds=100, option_load_limit_pct=50.00,
                         baseline_headcount=10, current_family_code="FAM_B")

        first_page, first_meta = validate_paginated(
            api.list_line_stations(plant.line_id, PRODUCTION_PLANNER_HEADERS,
                                   {"limit": 1, "offset": 0})
        )

        assert first_meta["total_count"] == 2
        assert first_meta["limit"] == 1
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True
        assert len(first_page) == 1
        assert first_page[0]["id"] == plant.st10_id

        second_page, second_meta = validate_paginated(
            api.list_line_stations(plant.line_id, PRODUCTION_PLANNER_HEADERS,
                                   {"limit": 1, "offset": 1})
        )

        assert second_meta["total_count"] == 2
        assert second_meta["offset"] == 1
        assert second_meta["has_more"] is False
        assert second_page[0]["id"] == plant.st20_id

        empty_page, empty_meta = validate_paginated(
            api.list_line_stations(other["id"], PRODUCTION_PLANNER_HEADERS)
        )

        assert empty_meta["total_count"] == 0
        assert empty_page == []

        _plans, plan_meta = validate_paginated(
            api.list_line_shift_plans(plant.line_id, PRODUCTION_PLANNER_HEADERS,
                                      {"shift_code": "A"})
        )
        assert plan_meta["total_count"] == 1
        _none, other_shift_meta = validate_paginated(
            api.list_line_shift_plans(plant.line_id, PRODUCTION_PLANNER_HEADERS,
                                      {"shift_code": "B"})
        )
        assert other_shift_meta["total_count"] == 0


class TestWarrantyClosure:
    """Closing files the analyst's note and confirms every charge already made."""

    def test_the_close_stores_the_note_and_leaves_every_counter_where_it_was(self, api):
        """One closure, one note, and no movement anywhere else.

        "Closing an analysed return takes it `ANALYZED_DESIGN → CLOSED` or
        `ANALYZED_SUPPLIER → CLOSED` and stores the optional `design_feedback_note`
        filed by the analyst. All analysis side effects stand; no counter is unwound."

        Design: Corner/endpoints/warranty_close_stores_the_design_feedback_note_and_freezes_counters
        """
        plant = base_plant_with_shift(api)
        unit = shipped_unit(api, plant, 1)
        set_clock(api, "2026-08-03T12:00:00Z")
        analysed = supplier_defect_return(api, plant, unit["id"],
                                          returned_at="2026-08-03T11:00:00Z")
        assert analysed["status"] == WarrantyReturnStatus.ANALYZED_SUPPLIER.value

        closed = validate_success(
            api.close_warranty_return(
                analysed["id"], WARRANTY_ANALYST_HEADERS,
                close_return_payload("seal supplier to requalify tooling"),
            )
        )

        assert closed["status"] == WarrantyReturnStatus.CLOSED.value
        assert closed["disposition"] == Disposition.SUPPLIER_DEFECT.value
        assert closed["root_cause_part_id"] == plant.part_id
        assert closed["engineering_change_id"] is None
        assert closed["design_feedback_note"] == "seal supplier to requalify tooling"
        part = read_part(api, plant.part_id)
        assert part["field_failure_count"] == 1
        assert float(part["cohort_failure_rate_per_1000"]) == approx2(1000.00)
        assert part["lifecycle_status"] == PartLifecycleStatus.ACTIVE.value
        supplier = read_supplier(api, plant.supplier_id)
        assert supplier["quality_penalty_count"] == 1
        assert float(supplier["on_time_score"]) == approx2(90.00)
        assert supplier["status"] == SupplierStatus.APPROVED.value

        validate_error(
            api.close_warranty_return(analysed["id"], WARRANTY_ANALYST_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
            expected_status=409,
        )

        assert read_return(api, analysed["id"])["design_feedback_note"] == \
            "seal supplier to requalify tooling"


class TestUnitAndTestFilters:
    """The appliance and its measurements are each addressable by their own facets."""

    def test_the_unit_facets_and_the_test_facets_each_select_the_right_rows(self, api):
        """One shipped appliance, five tests, and filters that agree with both.

        "Production units can be listed and filtered by `build_slot_id`,
        `assembly_status`, `quality_status` and `certification_tier`."

        "The tests of a unit can be listed and filtered by `test_type`, `status` and
        `result`."

        "`ENERGY` and `WATER` tests are never pass/fail at all: their `result` is always
        `MEASURED`, and they never quarantine a unit — they are scored at certification
        time instead."

        Design: Corner/endpoints/production_unit_and_quality_test_filters_compose
        """
        plant = base_plant_with_shift(api)
        unit = shipped_unit(api, plant, 1, energy=[380.00], water=[184.00])
        assert unit["certification_tier"] == CertificationTier.A.value

        shipped, shipped_meta = validate_paginated(
            api.list_production_units(
                QUALITY_INSPECTOR_HEADERS,
                {"assembly_status": AssemblyStatus.SHIPPED.value})
        )

        assert shipped_meta["total_count"] == 1
        assert shipped[0]["id"] == unit["id"]

        _none, pending_meta = validate_paginated(
            api.list_production_units(QUALITY_INSPECTOR_HEADERS,
                                      {"quality_status": QualityStatus.PENDING.value})
        )
        assert pending_meta["total_count"] == 0
        _tier_a, tier_a_meta = validate_paginated(
            api.list_production_units(
                QUALITY_INSPECTOR_HEADERS,
                {"certification_tier": CertificationTier.A.value})
        )
        assert tier_a_meta["total_count"] == 1
        _tier_b, tier_b_meta = validate_paginated(
            api.list_production_units(
                QUALITY_INSPECTOR_HEADERS,
                {"certification_tier": CertificationTier.B.value})
        )
        assert tier_b_meta["total_count"] == 0

        measured, measured_meta = validate_paginated(
            api.list_quality_tests(unit["id"], QUALITY_INSPECTOR_HEADERS,
                                   {"result": TestResult.MEASURED.value})
        )

        assert measured_meta["total_count"] == 2
        assert {row["test_type"] for row in measured} == \
            {TestType.ENERGY.value, TestType.WATER.value}

        energy, energy_meta = validate_paginated(
            api.list_quality_tests(unit["id"], QUALITY_INSPECTOR_HEADERS,
                                   {"test_type": TestType.ENERGY.value,
                                    "status": QualityTestStatus.RECORDED.value})
        )

        assert energy_meta["total_count"] == 1
        assert float(energy[0]["limit_value"]) == approx2(400.00)
        assert float(energy[0]["measured_value"]) == approx2(380.00)
        _voided, voided_meta = validate_paginated(
            api.list_quality_tests(unit["id"], QUALITY_INSPECTOR_HEADERS,
                                   {"status": QualityTestStatus.VOIDED.value})
        )
        assert voided_meta["total_count"] == 0


class TestCallAndChangeFilters:
    """Dock bookings and engineering changes answer on status and provenance."""

    def test_a_cancelled_call_a_live_call_and_a_manual_change_are_each_selectable(
            self, api):
        """Reason, station, origin and status all narrow to exactly one row.

        "Delivery calls can be listed and filtered by `supplier_id`, `part_id`,
        `station_id`, `status` and `cancel_reason`."

        "Engineering changes can be listed and filtered by `model_variant_id`,
        `affected_part_id`, `replacement_part_id`, `target_line_id`,
        `source_warranty_return_id`, `origin` and `status`, and a single-change read
        exposes `revision_round`, `submitted_by_user_id`, `decided_by_user_id` and
        `cut_in_at`."

        Design: Corner/endpoints/delivery_call_and_change_lists_filter_on_status_and_origin
        """
        plant = base_plant(api)
        doomed = new_delivery_call(api, plant.supplier_id, plant.part_id,
                                  plant.st10_id, "2026-08-03T09:00:00Z",
                                  "2026-08-03T10:00:00Z")
        live = new_delivery_call(api, plant.supplier_id, plant.part_id,
                                 plant.st10_id, "2026-08-03T11:00:00Z",
                                 "2026-08-03T12:00:00Z", sequenced_qty=4)
        cancel_call(api, doomed["id"])
        change = submitted_change(api, plant, make_engineering_lead_headers("eng-1"))
        assert change["origin"] == ChangeOrigin.MANUAL.value

        page, page_meta = validate_paginated(
            api.list_delivery_calls(PRODUCTION_PLANNER_HEADERS,
                                    {"supplier_id": plant.supplier_id,
                                     "limit": 1, "offset": 0})
        )

        assert page_meta["total_count"] == 2
        assert page_meta["has_more"] is True
        assert len(page) == 1

        cancelled, cancelled_meta = validate_paginated(
            api.list_delivery_calls(
                PRODUCTION_PLANNER_HEADERS,
                {"status": DeliveryCallStatus.CANCELLED.value})
        )

        assert cancelled_meta["total_count"] == 1
        assert cancelled[0]["id"] == doomed["id"]

        by_reason, reason_meta = validate_paginated(
            api.list_delivery_calls(PRODUCTION_PLANNER_HEADERS,
                                    {"cancel_reason": CancelReason.PLANNER.value})
        )

        assert reason_meta["total_count"] == 1
        assert by_reason[0]["id"] == doomed["id"]

        scheduled, scheduled_meta = validate_paginated(
            api.list_delivery_calls(
                PRODUCTION_PLANNER_HEADERS,
                {"status": DeliveryCallStatus.SCHEDULED.value,
                 "station_id": plant.st10_id})
        )

        assert scheduled_meta["total_count"] == 1
        assert scheduled[0]["id"] == live["id"]
        assert scheduled[0]["sequenced_qty"] == 4

        manual, manual_meta = validate_paginated(
            api.list_engineering_changes(
                PLANT_ADMIN_HEADERS,
                {"origin": ChangeOrigin.MANUAL.value,
                 "status": EngineeringChangeStatus.SUBMITTED.value})
        )

        assert manual_meta["total_count"] == 1
        assert manual[0]["id"] == change["id"]
        assert manual[0]["submitted_by_user_id"] == "eng-1"
        _no_warranty, warranty_meta = validate_paginated(
            api.list_engineering_changes(PLANT_ADMIN_HEADERS,
                                         {"origin": ChangeOrigin.WARRANTY.value})
        )
        assert warranty_meta["total_count"] == 0
