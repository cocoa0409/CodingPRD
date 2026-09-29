"""The appliance's own lifecycle, from minting to shipment.

A released slot mints a unit in a known compound state; the quality gates admit
measurements only in order; a failure quarantines both dimensions and clearing it
restarts the chain; and only shipment gives line-side capacity back.
"""

from test_helpers import (
    LINE_OPERATOR_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
    ApiErrorId,
    AssemblyStatus,
    BuildSlotStatus,
    CertificationTier,
    LinePosture,
    QualityStatus,
    QualityTestStatus,
    TestResult,
    TestType,
    approx2,
    assert_serial_number,
    base_plant_with_shift,
    certify,
    clear_quarantine_payload,
    complete_assembly,
    drive_unit_to_gated,
    gated_unit,
    quality_test_payload,
    read_line,
    read_shift_plan,
    read_slot,
    read_station,
    read_unit,
    record_test,
    released_unit,
    sequenced_slot,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestUnitMinting:
    """Releasing a slot to the floor is what creates the appliance."""

    def test_a_released_slot_mints_a_unit_in_its_initial_compound_state(self, api):
        """Both dimensions start at their first value, with a derived serial.

        "The unit starts with `assembly_status` `IN_STATION`, `quality_status`
        `PENDING`, `rework_count` 0, and null `provisional_efficiency_index`,
        `efficiency_index` and `certification_tier`."

        Design: Corner/state_machines/released_slot_creates_unit_in_initial_state
        """
        plant = base_plant_with_shift(api)
        sequenced_slot(api, plant, 1, "2026-08-03T07:00:00Z")

        unit = validate_success(
            api.release_build_slot(plant.slot_id(1), LINE_OPERATOR_HEADERS),
            expected_status=201,
        )

        assert unit["assembly_status"] == AssemblyStatus.IN_STATION.value
        assert unit["quality_status"] == QualityStatus.PENDING.value
        assert unit["rework_count"] == 0
        assert unit["build_slot_id"] == plant.slot_id(1)
        assert unit["built_at_sequence_index"] == 1
        assert unit["serial_number"] == "L1-000001"
        assert_serial_number(unit, "L1")
        assert unit["efficiency_index"] is None
        assert unit["certification_tier"] is None
        assert unit["provisional_efficiency_index"] is None
        assert read_slot(api, plant.slot_id(1))["status"] == BuildSlotStatus.RELEASED.value
        assert read_line(api, plant.line_id)["max_released_sequence_index"] == 1

    def test_certifying_a_pending_unit_is_refused(self, api):
        """Certification is reachable from one state only.

        "Certification, a quality-inspector action, moves the unit `GATED →
        CERTIFIED`. It requires `quality_status` to be `GATED`, the model variant to
        still be `RELEASED` (otherwise `ERR_MODEL_NOT_RELEASED`), and at least one
        `RECORDED` `ENERGY` test and at least one `RECORDED` `WATER` test to exist — a
        unit with only one of the two is refused with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/certify_unit_still_pending_returns_409
        """
        plant = base_plant_with_shift(api)
        unit = released_unit(api, plant, 1)

        validate_error(
            api.certify_unit(unit["id"], QUALITY_INSPECTOR_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
            expected_status=409,
        )

        after = read_unit(api, unit["id"])
        assert after["quality_status"] == QualityStatus.PENDING.value
        assert after["efficiency_index"] is None
        assert after["certification_tier"] is None


class TestQualityGateOrdering:
    """Electrical safety unlocks the rest of the chain, and nothing else does."""

    def test_a_functional_cycle_before_the_safety_pass_is_refused(self, api):
        """The gate order is checked before any measurement is stored.

        "Ordering is then enforced with `ERR_QUALITY_GATE_ORDER`:
        `ELECTRICAL_SAFETY` must come first, `LEAK` and `FUNCTIONAL_CYCLE` require a
        `quality_status` of `SAFETY_PASSED` or `GATED`, and `ENERGY` and `WATER`
        require a `quality_status` of `GATED`."

        Design: Corner/state_machines/functional_cycle_before_electrical_safety_rejected
        """
        plant = base_plant_with_shift(api)
        unit = released_unit(api, plant, 1)

        validate_error(
            api.record_quality_test(
                unit["id"], quality_test_payload(TestType.FUNCTIONAL_CYCLE.value, 3),
                QUALITY_INSPECTOR_HEADERS,
            ),
            ApiErrorId.ERR_QUALITY_GATE_ORDER,
            expected_status=409,
        )

        _rows, meta = validate_paginated(
            api.list_quality_tests(unit["id"], QUALITY_INSPECTOR_HEADERS)
        )
        assert meta["total_count"] == 0
        safety = record_test(api, unit["id"], TestType.ELECTRICAL_SAFETY.value, 0.30)
        assert float(safety["limit_value"]) == approx2(0.50)
        assert safety["result"] == TestResult.PASS.value
        assert read_unit(api, unit["id"])["quality_status"] == \
            QualityStatus.SAFETY_PASSED.value

        cycle = record_test(api, unit["id"], TestType.FUNCTIONAL_CYCLE.value, 3)

        assert float(cycle["limit_value"]) == approx2(3)
        assert cycle["result"] == TestResult.PASS.value
        # This variant requires a leak test, so the gate is not reached yet.
        assert read_unit(api, unit["id"])["quality_status"] == \
            QualityStatus.SAFETY_PASSED.value


class TestQuarantineAndClearance:
    """One failure moves both dimensions, and clearing it rewinds them."""

    def test_a_failed_safety_test_quarantines_the_unit_and_blocks_assembly(self, api):
        """A single FAIL result mutates the quality and assembly dimensions.

        "Any test whose `result` is `FAIL` quarantines the unit in a single mutation,
        from whichever quality state it was in: `PENDING → QUARANTINED`,
        `SAFETY_PASSED → QUARANTINED` or `GATED → QUARANTINED`. In the same mutation
        the assembly dimension moves to `REWORK` — `IN_STATION → REWORK` or
        `ASSEMBLED → REWORK` — and `rework_count` is incremented by one."

        Design: Corner/state_machines/failing_electrical_safety_test_quarantines_both_dimensions
        """
        plant = base_plant_with_shift(api)
        unit = released_unit(api, plant, 1)

        failed = record_test(api, unit["id"], TestType.ELECTRICAL_SAFETY.value, 0.60)

        assert failed["result"] == TestResult.FAIL.value
        assert float(failed["limit_value"]) == approx2(0.50)
        assert failed["status"] == QualityTestStatus.RECORDED.value
        quarantined = read_unit(api, unit["id"])
        assert quarantined["quality_status"] == QualityStatus.QUARANTINED.value
        assert quarantined["assembly_status"] == AssemblyStatus.REWORK.value
        assert quarantined["rework_count"] == 1

        validate_error(
            api.complete_assembly(unit["id"], LINE_OPERATOR_HEADERS),
            ApiErrorId.ERR_UNIT_QUARANTINED,
            expected_status=409,
        )

        assert read_unit(api, unit["id"])["assembly_status"] == \
            AssemblyStatus.REWORK.value
        # A quarantine is rework off the slot's books.
        assert read_slot(api, plant.slot_id(1))["status"] == BuildSlotStatus.RELEASED.value

    def test_clearing_the_quarantine_voids_the_failure_and_restarts_the_chain(self, api):
        """Both dimensions rewind, the counter does not, and the gate reopens.

        "It requires the unit to be in `REWORK` on the assembly dimension and
        `QUARANTINED` on the quality dimension, and it does three things: every
        quality test of that unit whose `result` is `FAIL` and whose `status` is still
        `RECORDED` becomes `VOIDED`; the quality dimension returns `QUARANTINED →
        PENDING`; and the assembly dimension returns `REWORK → IN_STATION`."

        Design: Corner/state_machines/clear_quarantine_voids_failures_and_restarts_the_gate_chain
        """
        plant = base_plant_with_shift(api)
        unit = released_unit(api, plant, 1)
        failed = record_test(api, unit["id"], TestType.ELECTRICAL_SAFETY.value, 0.60)

        cleared = validate_success(
            api.clear_quarantine(
                unit["id"], QUALITY_INSPECTOR_HEADERS,
                clear_quarantine_payload("connector reseated"),
            )
        )

        assert cleared["quality_status"] == QualityStatus.PENDING.value
        assert cleared["assembly_status"] == AssemblyStatus.IN_STATION.value
        assert cleared["rework_count"] == 1
        voided, _meta = validate_paginated(
            api.list_quality_tests(unit["id"], QUALITY_INSPECTOR_HEADERS)
        )
        assert [row["status"] for row in voided if row["id"] == failed["id"]] == \
            [QualityTestStatus.VOIDED.value]
        _rows, recorded_meta = validate_paginated(
            api.list_quality_tests(unit["id"], QUALITY_INSPECTOR_HEADERS,
                                   {"status": QualityTestStatus.RECORDED.value})
        )
        assert recorded_meta["total_count"] == 0

        validate_error(
            api.record_quality_test(
                unit["id"], quality_test_payload(TestType.FUNCTIONAL_CYCLE.value, 3),
                QUALITY_INSPECTOR_HEADERS,
            ),
            ApiErrorId.ERR_QUALITY_GATE_ORDER,
            expected_status=409,
        )

        record_test(api, unit["id"], TestType.ELECTRICAL_SAFETY.value, 0.30)
        assert read_unit(api, unit["id"])["quality_status"] == \
            QualityStatus.SAFETY_PASSED.value


class TestAssemblyAndShipment:
    """Completing assembly closes the slot; shipping frees the line side."""

    def test_completing_assembly_bubbles_the_slot_and_keeps_the_slots_committed(self, api):
        """The parent slot closes while the quality dimension stands still.

        "As a bubble-up side effect, the owning build slot moves `RELEASED → BUILT`:
        the slot is closed, but its presentation slots stay committed until the
        appliance actually leaves."

        Design: Corner/state_machines/complete_assembly_bubbles_the_slot_from_released_to_built
        """
        plant = base_plant_with_shift(api)
        unit = released_unit(api, plant, 1)

        assembled = validate_success(
            api.complete_assembly(unit["id"], LINE_OPERATOR_HEADERS)
        )

        assert assembled["assembly_status"] == AssemblyStatus.ASSEMBLED.value
        assert assembled["quality_status"] == QualityStatus.PENDING.value
        assert read_slot(api, plant.slot_id(1))["status"] == BuildSlotStatus.BUILT.value
        assert read_station(api, plant.st10_id)["presentation_slots_used"] == 2
        assert read_line(api, plant.line_id)["presentation_slots_committed"] == 2
        # A BUILT slot stays inside the labour input set.
        assert read_shift_plan(api, plant.shift_plan_id)["committed_labor_minutes"] == 150

    def test_shipping_hands_the_presentation_slots_back_to_the_line(self, api):
        """The only transition that reduces a station's used counter.

        "Shipping is the moment line-side capacity is finally given back: each station
        named in the slot's `presentation_allocations` has its
        `presentation_slots_used` reduced by the recorded `slot_units`, and the line's
        `presentation_slots_committed`, `free_slot_pct` and `posture` are re-derived."

        Design: Corner/state_machines/shipping_releases_presentation_slots_to_the_line_ledger
        """
        plant = base_plant_with_shift(api)
        unit = gated_unit(api, plant, 1)
        certified = certify(api, unit["id"])
        assert certified["certification_tier"] == CertificationTier.A.value
        complete_assembly(api, unit["id"])

        shipped = validate_success(
            api.ship_unit(unit["id"], LINE_OPERATOR_HEADERS)
        )

        assert shipped["assembly_status"] == AssemblyStatus.SHIPPED.value
        assert shipped["quality_status"] == QualityStatus.CERTIFIED.value
        assert read_station(api, plant.st10_id)["presentation_slots_used"] == 0
        assert read_station(api, plant.st20_id)["presentation_slots_used"] == 0
        line = read_line(api, plant.line_id)
        assert line["presentation_slots_committed"] == 0
        assert float(line["free_slot_pct"]) == approx2(100.00)
        assert line["posture"] == LinePosture.OPEN.value
        # The labour ledger is untouched, because the slot is still BUILT.
        assert read_shift_plan(api, plant.shift_plan_id)["committed_labor_minutes"] == 150
        assert read_slot(api, plant.slot_id(1))["status"] == BuildSlotStatus.BUILT.value

    def test_shipping_an_uncertified_unit_is_refused_and_frees_nothing(self, api):
        """The cross-dimension guard demands exactly CERTIFIED.

        "It moves `ASSEMBLED → SHIPPED` and requires `quality_status` to be exactly
        `CERTIFIED`; anything else is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/ship_unit_without_certification_returns_409
        """
        plant = base_plant_with_shift(api)
        unit = released_unit(api, plant, 1)
        drive_unit_to_gated(api, unit["id"])
        complete_assembly(api, unit["id"])
        assert read_unit(api, unit["id"])["quality_status"] == QualityStatus.GATED.value

        validate_error(
            api.ship_unit(unit["id"], LINE_OPERATOR_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
            expected_status=409,
        )

        after = read_unit(api, unit["id"])
        assert after["assembly_status"] == AssemblyStatus.ASSEMBLED.value
        assert after["quality_status"] == QualityStatus.GATED.value
        assert read_station(api, plant.st10_id)["presentation_slots_used"] == 2
        assert float(read_line(api, plant.line_id)["free_slot_pct"]) == approx2(97.50)
