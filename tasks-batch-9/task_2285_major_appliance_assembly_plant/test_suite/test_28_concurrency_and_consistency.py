"""Version tokens are single-use, and nothing in this plant settles later.

A token that has just been spent is stale on the very next call, even for a
write that could not possibly have collided; and every derived figure a mutation
touches is already in the body of the response that performed it.
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
    LinePosture,
    ModelVariantStatus,
    QualityStatus,
    ShiftPlanStatus,
    approx2,
    assert_slot_charges,
    base_plant_with_shift,
    bom_line_payload,
    drive_unit_to_gated,
    line_version,
    new_line,
    new_model_variant,
    new_part,
    new_station,
    new_supplier,
    planned_slot,
    read_line,
    read_shift_plan,
    read_station,
    read_variant,
    record_consumption,
    release_slot,
    set_clock,
    shift_plan_payload,
    validate_error,
    validate_paginated,
    validate_success,
    variant_version,
)


def _bare_line(api):
    """A line with its two stations and no plan, slot or variant yet."""
    set_clock(api, "2026-08-03T06:00:00Z")
    line = new_line(api, "L1")
    new_station(api, line["id"], "ST10", 10)
    new_station(api, line["id"], "ST20", 20)
    return line


def _draft_variant_plant(api):
    """A draft variant, its part and the two stations it could be built at."""
    line = _bare_line(api)
    supplier = new_supplier(api, "SUP1", "Hinge and Module Co",
                            sync_window_minutes=30)
    part = new_part(api, supplier["id"], "P-DOOR-A")
    variant = new_model_variant(api, "WM-X")
    stations, _meta = validate_paginated(
        api.list_line_stations(line["id"], PLANT_ADMIN_HEADERS)
    )
    return line, part, variant, stations


class TestShiftPlanVersionToken:
    """The line's version is spent by the plan that quotes it."""

    def test_the_token_that_just_worked_is_stale_on_the_following_plan(self, api):
        """Too high is refused, exactly right is accepted, and then it is spent.

        "Creating a shift plan requires `expected_line_version`, carrying the `version`
        of the target line as the client last observed it. If the line's current
        `version` differs, the request is rejected with `ERR_STALE_LINE_VERSION` and HTTP
        412."

        "`available_labor_minutes` is the shift's 480 base minutes plus its
        `overtime_minutes`; the line runs a single crew, so `planned_headcount` is
        emphatically **not** a factor in available minutes — its only role in this system
        is to scale the option-load window cap of §3.5."

        Design: Corner/cross_cutting_complexity_layers/occ_shift_plan_create_rejects_a_stale_line_version
        """
        line = _bare_line(api)
        observed = line_version(api, line["id"])

        validate_error(
            api.create_shift_plan(
                shift_plan_payload(line["id"], observed + 5),
                PRODUCTION_PLANNER_HEADERS,
            ),
            ApiErrorId.ERR_STALE_LINE_VERSION,
            expected_status=412,
        )

        _none, empty_meta = validate_paginated(
            api.list_line_shift_plans(line["id"], PRODUCTION_PLANNER_HEADERS)
        )
        assert empty_meta["total_count"] == 0

        accepted = validate_success(
            api.create_shift_plan(
                shift_plan_payload(line["id"], observed),
                PRODUCTION_PLANNER_HEADERS,
            ),
            expected_status=201,
        )

        assert accepted["status"] == ShiftPlanStatus.ACTIVE.value
        assert accepted["available_labor_minutes"] == 480

        # Shift B would not have overlapped shift A, but the token is gone.
        validate_error(
            api.create_shift_plan(
                shift_plan_payload(line["id"], observed, shift_code="B",
                                   shift_start="2026-08-03T14:00:00Z",
                                   shift_end="2026-08-03T22:00:00Z"),
                PRODUCTION_PLANNER_HEADERS,
            ),
            ApiErrorId.ERR_STALE_LINE_VERSION,
            expected_status=412,
        )

        assert read_line(api, line["id"])["version"] == observed + 1
        _plans, plan_meta = validate_paginated(
            api.list_line_shift_plans(line["id"], PRODUCTION_PLANNER_HEADERS)
        )
        assert plan_meta["total_count"] == 1


class TestBomLineVersionToken:
    """Authoring one position bumps the variant, so the next position needs a re-read."""

    def test_a_stale_variant_token_is_refused_before_and_after_the_accepted_line(
            self, api):
        """One accepted line between two refusals, and the variant still a draft.

        "Authoring a bill-of-materials line requires `expected_model_variant_version`,
        carrying the `version` of the target model variant as the client last observed
        it. If the variant's current `version` differs — because another writer has
        authored a line, released the variant, or made it obsolete since the client's
        last read — the request is rejected with `ERR_STALE_MODEL_VARIANT_VERSION` and
        HTTP 412."

        "A new line arrives with `status` `ACTIVE`, a null `superseded_by_bom_line_id`
        and a null `created_by_change_id` — the latter stays null for every manually
        authored line and is filled in only for lines minted by a cut-in."

        Design: Corner/cross_cutting_complexity_layers/occ_bom_line_create_rejects_a_stale_model_variant_version
        """
        _line, part, variant, stations = _draft_variant_plant(api)
        observed = variant_version(api, variant["id"])
        st10, st20 = stations[0]["id"], stations[1]["id"]

        validate_error(
            api.create_bom_line(
                bom_line_payload(variant["id"], part["id"], st10, observed + 7,
                                 "POS-DOOR"),
                ENGINEERING_LEAD_HEADERS,
            ),
            ApiErrorId.ERR_STALE_MODEL_VARIANT_VERSION,
            expected_status=412,
        )

        _none, empty_meta = validate_paginated(
            api.list_bom_lines(ENGINEERING_LEAD_HEADERS,
                               {"model_variant_id": variant["id"]})
        )
        assert empty_meta["total_count"] == 0

        accepted = validate_success(
            api.create_bom_line(
                bom_line_payload(variant["id"], part["id"], st10, observed,
                                 "POS-DOOR"),
                ENGINEERING_LEAD_HEADERS,
            ),
            expected_status=201,
        )

        assert accepted["status"] == BomLineStatus.ACTIVE.value
        assert accepted["superseded_by_bom_line_id"] is None
        assert accepted["created_by_change_id"] is None

        # A different position at a different station, but the same spent token.
        validate_error(
            api.create_bom_line(
                bom_line_payload(variant["id"], part["id"], st20, observed,
                                 "POS-LID", qty_per_unit=1),
                ENGINEERING_LEAD_HEADERS,
            ),
            ApiErrorId.ERR_STALE_MODEL_VARIANT_VERSION,
            expected_status=412,
        )

        after = read_variant(api, variant["id"])
        assert after["version"] == observed + 1
        assert after["status"] == ModelVariantStatus.DRAFT.value
        _lines, line_meta = validate_paginated(
            api.list_bom_lines(ENGINEERING_LEAD_HEADERS,
                               {"model_variant_id": variant["id"]})
        )
        assert line_meta["total_count"] == 1


class TestImmediateVisibility:
    """Whatever a mutation derived is already in the body it answered with."""

    def test_the_sequencing_and_certification_bodies_need_no_follow_up_read(self, api):
        """Every follow-up read merely confirms what the mutation already reported.

        "Unless otherwise noted, operations that create or modify a resource will return
        the created or updated resource object in the data field."

        "`presentation_allocations` records one object per charged station, each carrying
        that `station_id` and its `slot_units`, and `allocated_slot_units` records their
        sum."

        "On success, `efficiency_index` and `certification_tier` are both written from
        the certification variant."

        Design: Corner/consistency_model/immediate_consistency_every_derived_field_is_visible_in_the_same_response
        """
        plant = base_plant_with_shift(api)
        planned_slot(api, plant, 1, "2026-08-03T07:00:00Z")

        sequenced = validate_success(
            api.sequence_build_slot(plant.slot_id(1), PRODUCTION_PLANNER_HEADERS)
        )

        assert sequenced["status"] == BuildSlotStatus.SEQUENCED.value
        assert sequenced["shift_plan_id"] == plant.shift_plan_id
        assert len(sequenced["presentation_allocations"]) == 1
        assert_slot_charges(sequenced, plant.st10_id, 2, 150, 4)

        # Nothing settles afterwards: the reads only echo the response above.
        assert read_station(api, plant.st10_id)["presentation_slots_used"] == 2
        line = read_line(api, plant.line_id)
        assert line["presentation_slots_committed"] == 2
        assert float(line["free_slot_pct"]) == approx2(97.50)
        assert line["posture"] == LinePosture.OPEN.value
        plan = read_shift_plan(api, plant.shift_plan_id)
        assert plan["unit_labor_minutes"] == 150
        assert plan["committed_labor_minutes"] == 150

        unit = release_slot(api, plant.slot_id(1))
        drive_unit_to_gated(api, unit["id"])
        record_consumption(api, unit["id"])

        certified = validate_success(
            api.certify_unit(unit["id"], QUALITY_INSPECTOR_HEADERS)
        )

        assert certified["quality_status"] == QualityStatus.CERTIFIED.value
        assert float(certified["efficiency_index"]) == approx2(0.94)
        assert certified["certification_tier"] == CertificationTier.A.value
