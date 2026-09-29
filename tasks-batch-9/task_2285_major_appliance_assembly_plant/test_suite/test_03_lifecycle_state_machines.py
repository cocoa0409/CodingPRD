"""Lifecycles that are not straight lines: a parallel pair, a counted loop and a
branch whose two arms touch disjoint records.

A production unit runs two dimensions at once, an engineering change cycles back
through review a bounded number of times, and a warranty analysis forks into two
outcomes that share no side effects at all.
"""

from test_helpers import (
    LINE_OPERATOR_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
    WARRANTY_ANALYST_HEADERS,
    ApiErrorId,
    AssemblyStatus,
    BuildSlotStatus,
    ChangeDecision,
    ChangeOrigin,
    Disposition,
    EngineeringChangeStatus,
    PartLifecycleStatus,
    QualityStatus,
    QualityTestStatus,
    SupplierStatus,
    TestResult,
    TestType,
    WarrantyReturnStatus,
    analyze_payload,
    approx2,
    base_plant,
    base_plant_with_shift,
    clear_quarantine_payload,
    decide_payload,
    draft_change,
    make_engineering_lead_headers,
    pass_safety_test,
    read_change,
    read_part,
    read_slot,
    read_supplier,
    read_unit,
    record_test,
    released_unit,
    set_clock,
    shipped_unit,
    torn_down_return,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProductionUnitTwoDimensions:
    """Assembly and quality advance on their own clocks and can move backwards."""

    def test_assembly_reaches_assembled_while_quality_is_still_walking_its_gates(self, api):
        """Completing assembly closes the slot and leaves the gates untouched.

        "The quality dimension is left entirely untouched. As a bubble-up side
        effect, the owning build slot moves `RELEASED → BUILT`: the slot is closed,
        but its presentation slots stay committed until the appliance actually
        leaves."

        Design: Difficulty/non_linear_state_machine/production_unit_assembly_and_quality_dimensions_advance_independently
        """
        plant = base_plant_with_shift(api)
        unit = released_unit(api, plant, 1)
        pass_safety_test(api, unit["id"], 0.30)

        assembled = validate_success(
            api.complete_assembly(unit["id"], LINE_OPERATOR_HEADERS)
        )

        assert assembled["assembly_status"] == AssemblyStatus.ASSEMBLED.value
        assert assembled["quality_status"] == QualityStatus.SAFETY_PASSED.value
        assert read_slot(api, plant.slot_id(1))["status"] == BuildSlotStatus.BUILT.value

        # A passing cycle test alone is not enough for a leak-bearing variant.
        after_cycle = record_test(api, unit["id"], TestType.FUNCTIONAL_CYCLE.value, 3)
        assert after_cycle["result"] == TestResult.PASS.value
        assert read_unit(api, unit["id"])["quality_status"] == QualityStatus.SAFETY_PASSED.value

        record_test(api, unit["id"], TestType.LEAK.value, 1.10)
        gated = read_unit(api, unit["id"])
        assert gated["quality_status"] == QualityStatus.GATED.value
        assert gated["assembly_status"] == AssemblyStatus.ASSEMBLED.value

    def test_failing_test_drags_assembly_back_and_clearing_restarts_both(self, api):
        """A late leak failure reworks an assembled unit, then the pair resets.

        "In the same mutation the assembly dimension moves to `REWORK` —
        `IN_STATION → REWORK` or `ASSEMBLED → REWORK` — and `rework_count` is
        incremented by one. When the unit was already `ASSEMBLED`, its build slot
        stays `BUILT`; the rework happens off the slot's books."

        Design: Difficulty/non_linear_state_machine/production_unit_assembly_and_quality_dimensions_advance_independently
        """
        plant = base_plant_with_shift(api)
        unit = released_unit(api, plant, 1)
        pass_safety_test(api, unit["id"], 0.30)
        validate_success(api.complete_assembly(unit["id"], LINE_OPERATOR_HEADERS))
        record_test(api, unit["id"], TestType.FUNCTIONAL_CYCLE.value, 3)
        record_test(api, unit["id"], TestType.LEAK.value, 1.10)

        failure = record_test(api, unit["id"], TestType.LEAK.value, 2.50)
        assert failure["result"] == TestResult.FAIL.value

        quarantined = read_unit(api, unit["id"])
        assert quarantined["quality_status"] == QualityStatus.QUARANTINED.value
        assert quarantined["assembly_status"] == AssemblyStatus.REWORK.value
        assert quarantined["rework_count"] == 1
        assert read_slot(api, plant.slot_id(1))["status"] == BuildSlotStatus.BUILT.value

        cleared = validate_success(
            api.clear_quarantine(unit["id"], QUALITY_INSPECTOR_HEADERS,
                                 clear_quarantine_payload("reseal and retest"))
        )

        assert cleared["assembly_status"] == AssemblyStatus.IN_STATION.value
        assert cleared["quality_status"] == QualityStatus.PENDING.value
        assert cleared["rework_count"] == 1
        voided, _ = validate_paginated(
            api.list_quality_tests(unit["id"], QUALITY_INSPECTOR_HEADERS,
                                   {"status": QualityTestStatus.VOIDED.value})
        )
        assert len(voided) == 1
        assert float(voided[0]["measured_value"]) == approx2(2.50)
        leaks, _ = validate_paginated(
            api.list_quality_tests(unit["id"], QUALITY_INSPECTOR_HEADERS,
                                   {"test_type": TestType.LEAK.value,
                                    "status": QualityTestStatus.RECORDED.value})
        )
        assert [float(t["measured_value"]) for t in leaks] == [approx2(1.10)]


class TestEngineeringChangeRevisionLoop:
    """The review loop is a cycle with a counter that ends it."""

    def _loop(self, api, change_id, alice, bob, rounds):
        """Push the change round the submit / review / request-revision cycle."""
        last = None
        for round_number in range(1, rounds + 1):
            validate_success(api.submit_engineering_change(change_id, alice))
            validate_success(api.start_review_engineering_change(change_id, alice))
            last = validate_success(
                api.decide_engineering_change(
                    change_id,
                    decide_payload(ChangeDecision.REQUEST_REVISION.value,
                                   f"round {round_number}"),
                    bob,
                )
            )
        return last

    def test_three_revisions_stay_in_the_loop(self, api):
        """The third request for revision still returns to REVISION_REQUESTED.

        "`REQUEST_REVISION` normally moves it `UNDER_REVIEW → REVISION_REQUESTED`
        with `revision_round` incremented by one, and the change re-enters the loop
        through a fresh submission."

        Design: Difficulty/non_linear_state_machine/engineering_change_revision_loop_cancels_at_round_cap
        """
        plant = base_plant(api)
        change = draft_change(api, plant, cut_in_sequence_index=5)
        alice = make_engineering_lead_headers("eng-alice")
        bob = make_engineering_lead_headers("eng-bob")

        third = self._loop(api, change["id"], alice, bob, 3)

        assert third["status"] == EngineeringChangeStatus.REVISION_REQUESTED.value
        assert third["revision_round"] == 3
        assert third["submitted_by_user_id"] == "eng-alice"
        assert third["decided_by_user_id"] == "eng-bob"

    def test_fourth_revision_cancels_the_change_and_frees_the_part(self, api):
        """Round four lands in terminal CANCELLED and releases the hold.

        "The loop is capped at three revision rounds: when the increment would
        carry `revision_round` beyond 3, the change instead moves
        `UNDER_REVIEW → CANCELLED`, `revision_round` is nonetheless recorded as 4,
        the loop is abandoned rather than returning to `REVISION_REQUESTED`, and the
        affected part returns `CHANGE_PENDING → ACTIVE` when no other live change
        names it."

        Design: Difficulty/non_linear_state_machine/engineering_change_revision_loop_cancels_at_round_cap
        """
        plant = base_plant(api)
        change = draft_change(api, plant, cut_in_sequence_index=5)
        alice = make_engineering_lead_headers("eng-alice")
        bob = make_engineering_lead_headers("eng-bob")

        fourth = self._loop(api, change["id"], alice, bob, 4)

        assert fourth["status"] == EngineeringChangeStatus.CANCELLED.value
        assert fourth["revision_round"] == 4
        assert fourth["status"] != EngineeringChangeStatus.REVISION_REQUESTED.value
        assert read_part(api, plant.part_id)["lifecycle_status"] == \
            PartLifecycleStatus.ACTIVE.value
        validate_error(
            api.submit_engineering_change(change["id"], alice),
            ApiErrorId.ERR_INVALID_STATE,
        )
        assert read_change(api, change["id"])["revision_round"] == 4


class TestWarrantyDispositionBranches:
    """Two dispositions from the same TEARDOWN state, two disjoint effect sets."""

    def _two_returns_in_teardown(self, api):
        plant = base_plant_with_shift(api)
        shipped_unit(api, plant, 1)
        shipped_unit(api, plant, 2, planned_start="2026-08-03T08:00:00Z",
                     safety=0.31, leak=1.20)
        set_clock(api, "2026-08-03T12:00:00Z")
        wr1 = torn_down_return(api, plant, plant.unit_id(1),
                               failure_code="F-DOOR-HINGE", field_hours=500,
                               returned_at="2026-08-03T11:00:00Z")
        wr2 = torn_down_return(api, plant, plant.unit_id(2),
                               failure_code="F-DOOR-HINGE", field_hours=400,
                               returned_at="2026-08-03T11:30:00Z")
        return plant, wr1, wr2

    def test_supplier_branch_charges_the_supplier_and_mints_no_change(self, api):
        """SUPPLIER_DEFECT costs ten score points and leaves no change behind.

        "Crucially, **no** engineering change is minted on this branch and
        `engineering_change_id` stays null; that is the whole divergence from the
        design branch."

        Design: Difficulty/non_linear_state_machine/warranty_disposition_branches_produce_divergent_side_effects
        """
        plant, wr1, _wr2 = self._two_returns_in_teardown(api)

        analysed = validate_success(
            api.analyze_warranty_return(
                wr1["id"],
                analyze_payload(Disposition.SUPPLIER_DEFECT.value, plant.part_id),
                WARRANTY_ANALYST_HEADERS,
            )
        )

        assert analysed["status"] == WarrantyReturnStatus.ANALYZED_SUPPLIER.value
        assert analysed["engineering_change_id"] is None
        supplier = read_supplier(api, plant.supplier_id)
        assert supplier["quality_penalty_count"] == 1
        assert float(supplier["on_time_score"]) == approx2(90.00)
        assert supplier["status"] == SupplierStatus.APPROVED.value
        _rows, meta = validate_paginated(
            api.list_engineering_changes(WARRANTY_ANALYST_HEADERS,
                                         {"source_warranty_return_id": wr1["id"]})
        )
        assert meta["total_count"] == 0

    def test_design_branch_mints_a_warranty_change_and_spares_the_supplier(self, api):
        """DESIGN_DEFECT raises a SUBMITTED change and charges nobody.

        "Because that change is already `SUBMITTED`, it moves the root-cause part
        `ACTIVE → CHANGE_PENDING`, which in turn blocks further sequencing of every
        variant whose effective bill of materials contains that part."

        Design: Difficulty/non_linear_state_machine/warranty_disposition_branches_produce_divergent_side_effects
        """
        plant, wr1, wr2 = self._two_returns_in_teardown(api)
        validate_success(
            api.analyze_warranty_return(
                wr1["id"],
                analyze_payload(Disposition.SUPPLIER_DEFECT.value, plant.part_id),
                WARRANTY_ANALYST_HEADERS,
            )
        )

        analysed = validate_success(
            api.analyze_warranty_return(
                wr2["id"],
                analyze_payload(Disposition.DESIGN_DEFECT.value, plant.part_id),
                WARRANTY_ANALYST_HEADERS,
            )
        )

        assert analysed["status"] == WarrantyReturnStatus.ANALYZED_DESIGN.value
        assert analysed["engineering_change_id"] is not None
        minted, meta = validate_paginated(
            api.list_engineering_changes(WARRANTY_ANALYST_HEADERS,
                                         {"source_warranty_return_id": wr2["id"]})
        )
        assert meta["total_count"] == 1
        assert minted[0]["status"] == EngineeringChangeStatus.SUBMITTED.value
        assert minted[0]["origin"] == ChangeOrigin.WARRANTY.value
        assert minted[0]["affected_part_id"] == plant.part_id
        assert minted[0]["replacement_part_id"] is None
        part = read_part(api, plant.part_id)
        assert part["field_failure_count"] == 2
        assert float(part["cohort_failure_rate_per_1000"]) == approx2(1000.00)
        assert part["lifecycle_status"] == PartLifecycleStatus.CHANGE_PENDING.value
        # The design branch charges no supplier: the score is the one the earlier
        # supplier-defect analysis left behind.
        assert float(read_supplier(api, plant.supplier_id)["on_time_score"]) == approx2(90.00)
