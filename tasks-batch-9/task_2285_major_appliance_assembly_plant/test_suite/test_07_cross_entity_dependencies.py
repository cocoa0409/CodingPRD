"""Verdicts that depend on the state of an entity the request never names.

Whether a build slot may go to the floor is decided by a station's counter
travelling through the line's posture, and whether a unit may be certified is
decided by its model variant's lifecycle — which leaves assembly untouched.
"""

from test_helpers import (
    LINE_OPERATOR_HEADERS,
    PLANT_ADMIN_HEADERS,
    PRODUCTION_PLANNER_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
    ApiErrorId,
    AssemblyStatus,
    BuildSlotStatus,
    LineOperatingMode,
    LinePosture,
    ModelVariantStatus,
    Plant,
    QualityStatus,
    approx2,
    base_plant_with_shift,
    de_sequence_slot,
    gated_unit,
    new_line,
    new_part,
    new_shift_plan,
    new_station,
    new_supplier,
    plain_variant,
    planned_slot,
    read_line,
    read_slot,
    read_station,
    read_unit,
    read_variant,
    sequence_slot,
    set_clock,
    validate_error,
    validate_success,
)


def _line_with_one_two_slot_station(api):
    """Line L2 carries a single station whose whole capacity is two units.

    WM-C charges ceil(1 x 20 / 10) = 2 units there and so saturates it, while
    WM-D charges ceil(1 x 20 / 20) = 1 and leaves a unit free.
    """
    plant = Plant()
    set_clock(api, "2026-08-03T06:00:00Z")
    plant.supplier = new_supplier(api, "SUP1", "Hinge and Module Co",
                                 sync_window_minutes=30)
    plant.suppliers["SUP1"] = plant.supplier
    plant.line = new_line(api, "L2")
    plant.stations["ST-A"] = new_station(
        api, plant.line_id, "ST-A", 10,
        presentation_slot_capacity=2, station_cycle_seconds=110,
    )
    station_id = plant.stations["ST-A"]["id"]
    plant.parts["P-SMALL"] = new_part(
        api, plant.supplier_id, "P-SMALL",
        is_sequenced_module=False, line_side_max_units=10,
    )
    plant.parts["P-BIG"] = new_part(
        api, plant.supplier_id, "P-BIG",
        is_sequenced_module=False, line_side_max_units=20,
    )
    wm_c = plain_variant(api, plant, "WM-C", 1, 100,
                        part_id=plant.parts["P-SMALL"]["id"],
                        station_id=station_id, bom_position_code="POS-BODY")
    wm_d = plain_variant(api, plant, "WM-D", 1, 100,
                        part_id=plant.parts["P-BIG"]["id"],
                        station_id=station_id, bom_position_code="POS-BODY")
    plant.shift_plan = new_shift_plan(api, plant.line_id, planned_headcount=20)
    planned_slot(api, plant, 1, "2026-08-03T07:00:00Z", wm_c["id"])
    planned_slot(api, plant, 2, "2026-08-03T07:30:00Z", wm_d["id"])
    return plant, station_id


class TestStationSaturationGatesSlotRelease:
    """A saturated station constrains the line, which blocks the floor."""

    def test_a_saturated_station_constrains_the_line_and_refuses_release(self, api):
        """The slot may be sequenced into a full station but not released.

        "A `CONSTRAINED` line still permits build slots to be sequenced — planning
        ahead into a tight line is legitimate — but blocks any slot from being
        released to the floor. A `STOPPED` line blocks both. Both refusals carry
        `ERR_LINE_POSTURE_BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/station_saturation_derives_line_posture_and_blocks_slot_release
        """
        plant, station_id = _line_with_one_two_slot_station(api)

        sequenced = validate_success(
            api.sequence_build_slot(plant.slot_id(1), PRODUCTION_PLANNER_HEADERS)
        )

        assert sequenced["allocated_slot_units"] == 2
        assert read_station(api, station_id)["presentation_slots_used"] == 2
        line = read_line(api, plant.line_id)
        assert float(line["free_slot_pct"]) == approx2(0.00)
        assert line["posture"] == LinePosture.CONSTRAINED.value
        assert line["operating_mode"] == LineOperatingMode.RUNNING.value

        validate_error(
            api.release_build_slot(plant.slot_id(1), LINE_OPERATOR_HEADERS),
            ApiErrorId.ERR_LINE_POSTURE_BLOCKED,
            expected_status=409,
        )

        assert read_slot(api, plant.slot_id(1))["status"] == BuildSlotStatus.SEQUENCED.value

    def test_leaving_one_unit_of_station_capacity_free_admits_the_release(self, api):
        """Freeing the station reopens the line and the sibling slot releases.

        "Otherwise, if any station on the line has a `presentation_slots_used` equal
        to its `presentation_slot_capacity` while that capacity is greater than
        zero, `posture` is `CONSTRAINED`."

        Design: Difficulty/cross_entity_state_dependency/station_saturation_derives_line_posture_and_blocks_slot_release
        """
        plant, station_id = _line_with_one_two_slot_station(api)
        sequence_slot(api, plant.slot_id(1))
        de_sequence_slot(api, plant.slot_id(1))
        reopened = read_line(api, plant.line_id)
        assert read_station(api, station_id)["presentation_slots_used"] == 0
        assert float(reopened["free_slot_pct"]) == approx2(100.00)
        assert reopened["posture"] == LinePosture.OPEN.value

        validate_success(
            api.sequence_build_slot(plant.slot_id(2), PRODUCTION_PLANNER_HEADERS)
        )
        half_full = read_line(api, plant.line_id)
        assert read_station(api, station_id)["presentation_slots_used"] == 1
        assert float(half_full["free_slot_pct"]) == approx2(50.00)
        assert half_full["posture"] == LinePosture.OPEN.value

        unit = validate_success(
            api.release_build_slot(plant.slot_id(2), LINE_OPERATOR_HEADERS),
            expected_status=201,
        )

        assert unit["assembly_status"] == AssemblyStatus.IN_STATION.value
        assert unit["quality_status"] == QualityStatus.PENDING.value
        assert unit["built_at_sequence_index"] == 2
        assert unit["serial_number"] == "L2-000002"
        assert read_slot(api, plant.slot_id(2))["status"] == BuildSlotStatus.RELEASED.value
        assert read_line(api, plant.line_id)["max_released_sequence_index"] == 2


class TestObsoleteVariantGatesOnlyTheQualityDimension:
    """Retiring the variant stops certification and nothing else."""

    def _gated_unit_of_an_obsolete_variant(self, api):
        plant = base_plant_with_shift(api)
        unit = gated_unit(api, plant, 1)
        validate_success(
            api.obsolete_model_variant(plant.variant_id, PLANT_ADMIN_HEADERS)
        )
        return plant, unit

    def test_certification_is_refused_once_the_variant_is_obsolete(self, api):
        """The gate lives on the variant, not on the unit.

        "Obsoleting, legal only from `RELEASED`, moves it `RELEASED → OBSOLETE` and
        advances its `version`; afterwards, further build-slot sequencing, further
        bill-of-materials authoring and certification of units of that variant are
        all refused with `ERR_MODEL_NOT_RELEASED`, while units already released keep
        building through to shipment."

        Design: Difficulty/cross_entity_state_dependency/obsoleting_the_variant_blocks_certification_but_not_assembly
        """
        plant, unit = self._gated_unit_of_an_obsolete_variant(api)
        assert read_variant(api, plant.variant_id)["status"] == \
            ModelVariantStatus.OBSOLETE.value

        validate_error(
            api.certify_unit(unit["id"], QUALITY_INSPECTOR_HEADERS),
            ApiErrorId.ERR_MODEL_NOT_RELEASED,
            expected_status=409,
        )

        after = read_unit(api, unit["id"])
        assert after["quality_status"] == QualityStatus.GATED.value
        assert after["efficiency_index"] is None
        assert after["certification_tier"] is None
        assert float(after["provisional_efficiency_index"]) == approx2(0.94)

    def test_assembly_still_completes_on_the_very_same_unit(self, api):
        """The assembly dimension carries no variant-status precondition.

        "Completing assembly, a line-operator action, moves `IN_STATION →
        ASSEMBLED` provided the unit's `quality_status` is not `QUARANTINED` — a
        quarantined unit is refused with `ERR_UNIT_QUARANTINED`."

        Design: Difficulty/cross_entity_state_dependency/obsoleting_the_variant_blocks_certification_but_not_assembly
        """
        plant, unit = self._gated_unit_of_an_obsolete_variant(api)

        assembled = validate_success(
            api.complete_assembly(unit["id"], LINE_OPERATOR_HEADERS)
        )

        assert assembled["assembly_status"] == AssemblyStatus.ASSEMBLED.value
        assert assembled["quality_status"] == QualityStatus.GATED.value
        assert read_slot(api, plant.slot_id(1))["status"] == BuildSlotStatus.BUILT.value
        # The presentation slots stay committed until the appliance ships.
        assert read_station(api, plant.st10_id)["presentation_slots_used"] == 2
