"""One rung of the validation ladder at a time.

Every request that could break several rules at once breaks exactly one of them
as far as the client is concerned: the lowest-numbered rule wins, nothing is
written, and the observable state afterwards proves the rejection cost nothing.
"""

from test_helpers import (
    BASE_CLOCK,
    ENGINEERING_LEAD_HEADERS,
    LINE_OPERATOR_HEADERS,
    NO_USER_ID_HEADERS,
    PLANT_ADMIN_HEADERS,
    PRODUCTION_PLANNER_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
    OMIT,
    ApiErrorId,
    AssemblyStatus,
    BomLineStatus,
    BuildSlotStatus,
    ChangeDecision,
    DeliveryCallStatus,
    EngineeringChangeStatus,
    PartLifecycleStatus,
    QualityStatus,
    QualityTestStatus,
    TestResult,
    TestType,
    approx2,
    approved_change,
    base_plant,
    base_plant_with_shift,
    bom_line_payload,
    build_slot_payload,
    cancel_call,
    clear_quarantine_payload,
    decide_payload,
    delivery_call_payload,
    get_success_data,
    line_payload,
    make_engineering_lead_headers,
    module_plant,
    new_delivery_call,
    new_line,
    new_part,
    new_station,
    planned_slot,
    quality_test_payload,
    quarantined_unit,
    read_change,
    read_line,
    read_part,
    read_shift_plan,
    read_slot,
    read_station,
    read_unit,
    read_variant,
    record_test,
    released_unit,
    released_variant,
    run_checkpoint,
    same_instant,
    sequence_many,
    set_clock,
    station_payload,
    stop_line,
    submitted_change,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    variant_version,
)

#: Well-formed identifiers that belong to no record in the plant.
_MISSING_LINE_ID = "00000000-0000-4000-8000-000000000001"
_MISSING_VARIANT_ID = "00000000-0000-4000-8000-000000000002"
_MISSING_PART_ID = "00000000-0000-4000-8000-000000000003"


def _dry_variant_plant(api):
    """A plant whose WM-D appliance carries no water at all.

    The variant needs no leak test and declares no water limit, but it does
    declare an energy limit, so energy is the only consumption measurement it
    can ever accept.
    """
    plant = base_plant_with_shift(api)
    dry = released_variant(
        api, plant, "WM-D", plant.part_id, plant.st10_id,
        bom_position_code="POS-DOOR", qty_per_unit=1,
        option_codes=["OPT-D"], option_content_points=2, labor_minutes=100,
        functional_cycle_count_required=1, hipot_leakage_ma_limit=0.50,
        energy_kwh_limit=400.00, requires_leak_test=OMIT,
        leak_limit_ml_per_min=OMIT, water_liters_limit=OMIT,
    )
    return plant, dry


class TestTestApplicability:
    """What may be measured is a property of the variant, not of the unit."""

    def test_a_dry_variant_refuses_leak_and_water_but_accepts_energy(self, api):
        """Two refusals, one acceptance, and a certification that can never happen.

        "Test applicability on quality-test recording: a `LEAK` test only when the
        model variant has `requires_leak_test` true, and a `WATER` test only when the
        variant's `water_liters_limit` is not null — otherwise
        `ERR_TEST_NOT_APPLICABLE`."

        "The server snapshots the governing limit onto the record as `limit_value`,
        taken from the model variant's `hipot_leakage_ma_limit`,
        `leak_limit_ml_per_min`, `functional_cycle_count_required`, `energy_kwh_limit`
        or `water_liters_limit` according to the `test_type`, so that later re-limits
        of the variant never rewrite history."

        Design: Corner/validations/leak_and_water_tests_not_applicable_to_a_dry_variant
        """
        plant, dry = _dry_variant_plant(api)
        stored = read_variant(api, dry["id"])
        assert stored["requires_leak_test"] is False
        assert stored["water_liters_limit"] is None
        unit = released_unit(api, plant, 1, variant_id=dry["id"])
        record_test(api, unit["id"], TestType.ELECTRICAL_SAFETY.value, 0.30)
        record_test(api, unit["id"], TestType.FUNCTIONAL_CYCLE.value, 1)
        assert read_unit(api, unit["id"])["quality_status"] == QualityStatus.GATED.value

        validate_error(
            api.record_quality_test(
                unit["id"], quality_test_payload(TestType.LEAK.value, 1.00),
                QUALITY_INSPECTOR_HEADERS,
            ),
            ApiErrorId.ERR_TEST_NOT_APPLICABLE,
            expected_status=422,
        )
        validate_error(
            api.record_quality_test(
                unit["id"], quality_test_payload(TestType.WATER.value, 100.00),
                QUALITY_INSPECTOR_HEADERS,
            ),
            ApiErrorId.ERR_TEST_NOT_APPLICABLE,
            expected_status=422,
        )

        energy = validate_success(
            api.record_quality_test(
                unit["id"], quality_test_payload(TestType.ENERGY.value, 380.00),
                QUALITY_INSPECTOR_HEADERS,
            ),
            expected_status=201,
        )

        assert energy["test_type"] == TestType.ENERGY.value
        assert float(energy["limit_value"]) == approx2(400.00)
        assert float(energy["measured_value"]) == approx2(380.00)
        assert energy["result"] == TestResult.MEASURED.value
        assert energy["status"] == QualityTestStatus.RECORDED.value

        # Certification wants a recorded water test, which this variant forbids.
        validate_error(
            api.certify_unit(unit["id"], QUALITY_INSPECTOR_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
            expected_status=409,
        )

        after = read_unit(api, unit["id"])
        assert after["quality_status"] == QualityStatus.GATED.value
        assert after["efficiency_index"] is None
        _rows, meta = validate_paginated(
            api.list_quality_tests(unit["id"], QUALITY_INSPECTOR_HEADERS)
        )
        assert meta["total_count"] == 3


class TestQuarantineBlocksEverything:
    """A quarantined appliance answers the same way to every attempt on it."""

    def test_a_quarantined_unit_accepts_nothing_until_the_quarantine_is_cleared(
            self, api):
        """Assembly, shipment and a fresh measurement are all refused at 409.

        "A quarantined unit accepts no assembly progress and no new measurement:
        assembly completion, shipping and quality-test recording on a unit whose
        `quality_status` is `QUARANTINED` are rejected with `ERR_UNIT_QUARANTINED`."

        "Completing assembly, a line-operator action, moves `IN_STATION → ASSEMBLED`
        provided the unit's `quality_status` is not `QUARANTINED` — a quarantined unit
        is refused with `ERR_UNIT_QUARANTINED`."

        Design: Corner/validations/quarantined_unit_rejects_assembly_progress_and_new_tests
        """
        plant = base_plant_with_shift(api)
        unit = quarantined_unit(api, plant, 1)
        failed, _meta = validate_paginated(
            api.list_quality_tests(unit["id"], QUALITY_INSPECTOR_HEADERS)
        )
        assert [row["status"] for row in failed] == [QualityTestStatus.RECORDED.value]

        validate_error(
            api.complete_assembly(unit["id"], LINE_OPERATOR_HEADERS),
            ApiErrorId.ERR_UNIT_QUARANTINED,
            expected_status=409,
        )
        # Shipping is named by the quarantine rule and by the from-state guard.
        ship_refusal = api.ship_unit(unit["id"], LINE_OPERATOR_HEADERS)
        assert ship_refusal.status_code == 409
        validate_error_is_one_of(
            ship_refusal,
            [ApiErrorId.ERR_UNIT_QUARANTINED, ApiErrorId.ERR_INVALID_STATE],
        )
        validate_error(
            api.record_quality_test(
                unit["id"],
                quality_test_payload(TestType.ELECTRICAL_SAFETY.value, 0.30),
                QUALITY_INSPECTOR_HEADERS,
            ),
            ApiErrorId.ERR_UNIT_QUARANTINED,
            expected_status=409,
        )

        blocked = read_unit(api, unit["id"])
        assert blocked["assembly_status"] == AssemblyStatus.REWORK.value
        assert blocked["quality_status"] == QualityStatus.QUARANTINED.value
        assert blocked["rework_count"] == 1

        cleared = validate_success(
            api.clear_quarantine(unit["id"], QUALITY_INSPECTOR_HEADERS,
                                 clear_quarantine_payload("harness reset"))
        )

        assert cleared["quality_status"] == QualityStatus.PENDING.value
        assert cleared["assembly_status"] == AssemblyStatus.IN_STATION.value
        voided, _voided_meta = validate_paginated(
            api.list_quality_tests(unit["id"], QUALITY_INSPECTOR_HEADERS)
        )
        assert [row["status"] for row in voided] == [QualityTestStatus.VOIDED.value]

        retest = validate_success(
            api.record_quality_test(
                unit["id"],
                quality_test_payload(TestType.ELECTRICAL_SAFETY.value, 0.30),
                QUALITY_INSPECTOR_HEADERS,
            ),
            expected_status=201,
        )

        assert retest["result"] == TestResult.PASS.value
        assert read_unit(api, unit["id"])["quality_status"] == \
            QualityStatus.SAFETY_PASSED.value
        assert read_slot(api, plant.slot_id(1))["status"] == BuildSlotStatus.RELEASED.value


class TestNaturalKeyScopes:
    """One duplicate code, two different scopes."""

    def test_line_codes_collide_globally_and_station_codes_only_within_a_line(
            self, api):
        """The same station code and position are free again on a second line.

        "Natural-key uniqueness: `line_code`, `model_code`, `supplier_code` and
        `part_number` are unique globally, and `station_code` and `position_index` are
        each unique within a line."

        Design: Corner/validations/duplicate_codes_are_global_for_lines_and_line_scoped_for_stations
        """
        set_clock(api, BASE_CLOCK)
        first = new_line(api, "L1")
        new_station(api, first["id"], "ST10", 10)

        validate_error(
            api.create_line(
                line_payload("L1", takt_seconds=90, option_load_limit_pct=50.00,
                             baseline_headcount=10, current_family_code="FAM_B"),
                PLANT_ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_CODE,
            expected_status=409,
        )
        validate_error(
            api.create_station(
                station_payload(first["id"], "ST10", 30), PLANT_ADMIN_HEADERS
            ),
            ApiErrorId.ERR_DUPLICATE_CODE,
            expected_status=409,
        )
        validate_error(
            api.create_station(
                station_payload(first["id"], "ST99", 10), PLANT_ADMIN_HEADERS
            ),
            ApiErrorId.ERR_DUPLICATE_CODE,
            expected_status=409,
        )

        second = validate_success(
            api.create_line(line_payload("L2"), PLANT_ADMIN_HEADERS),
            expected_status=201,
        )
        twin = validate_success(
            api.create_station(
                station_payload(second["id"], "ST10", 10), PLANT_ADMIN_HEADERS
            ),
            expected_status=201,
        )

        assert twin["station_code"] == "ST10"
        assert twin["position_index"] == 10
        assert twin["line_id"] == second["id"]
        _first_rows, first_meta = validate_paginated(
            api.list_line_stations(first["id"], PLANT_ADMIN_HEADERS)
        )
        assert first_meta["total_count"] == 1
        _second_rows, second_meta = validate_paginated(
            api.list_line_stations(second["id"], PLANT_ADMIN_HEADERS)
        )
        assert second_meta["total_count"] == 1


class TestSequenceIndexUniqueness:
    """A merely planned slot still owns its index until the sweep kills it."""

    def test_the_index_frees_up_only_once_the_checkpoint_cancels_the_stale_slot(
            self, api):
        """The same creation fails, then succeeds after the sweep.

        "`sequence_index` is unique per line among build slots whose `status` is
        `PLANNED`, `SEQUENCED`, `RELEASED` or `BUILT`, enforced when a build slot is
        created — otherwise `ERR_SEQUENCE_INDEX_TAKEN`."

        "Every build slot on the line still `PLANNED` whose `planned_start` is earlier
        than the logical clock becomes `CANCELLED`, freeing its `sequence_index`."

        Design: Corner/validations/sequence_index_stays_taken_until_the_checkpoint_cancels_the_stale_slot
        """
        plant = base_plant_with_shift(api)
        planned_slot(api, plant, 1, "2026-08-03T07:00:00Z")

        validate_error(
            api.create_build_slot(
                build_slot_payload(plant.line_id, plant.variant_id, 1,
                                   "2026-08-03T09:00:00Z"),
                PRODUCTION_PLANNER_HEADERS,
            ),
            ApiErrorId.ERR_SEQUENCE_INDEX_TAKEN,
            expected_status=409,
        )

        set_clock(api, "2026-08-03T08:00:00Z")
        report = run_checkpoint(api, plant.line_id)

        assert report["checkpoint_index"] == 1
        assert report["cancelled_build_slot_ids"] == [plant.slot_id(1)]
        assert read_slot(api, plant.slot_id(1))["status"] == \
            BuildSlotStatus.CANCELLED.value

        revived = validate_success(
            api.create_build_slot(
                build_slot_payload(plant.line_id, plant.variant_id, 1,
                                   "2026-08-03T09:00:00Z"),
                PRODUCTION_PLANNER_HEADERS,
            ),
            expected_status=201,
        )

        assert revived["sequence_index"] == 1
        assert revived["status"] == BuildSlotStatus.PLANNED.value
        line = read_line(api, plant.line_id)
        assert line["checkpoint_index"] == 1
        assert line["max_released_sequence_index"] == 0


class TestShiftCoverageBoundary:
    """The covering window is closed at its start and open at its end."""

    def test_a_slot_at_the_shift_start_sequences_and_one_at_its_end_does_not(
            self, api):
        """Two slots, eight hours apart, decided by the same plan.

        "Exactly one active shift plan of the line must cover the relevant instant:
        `planned_start` when sequencing a slot, the logical clock when a changeover is
        booked by starting the line — otherwise `ERR_NO_SHIFT_COVERAGE`."

        Design: Corner/validations/shift_coverage_is_inclusive_at_start_and_exclusive_at_end
        """
        plant = base_plant_with_shift(api)
        planned_slot(api, plant, 1, "2026-08-03T06:00:00Z")
        planned_slot(api, plant, 2, "2026-08-03T14:00:00Z")

        opening = validate_success(
            api.sequence_build_slot(plant.slot_id(1), PRODUCTION_PLANNER_HEADERS)
        )

        assert opening["status"] == BuildSlotStatus.SEQUENCED.value
        assert opening["shift_plan_id"] == plant.shift_plan_id

        validate_error(
            api.sequence_build_slot(plant.slot_id(2), PRODUCTION_PLANNER_HEADERS),
            ApiErrorId.ERR_NO_SHIFT_COVERAGE,
            expected_status=422,
        )

        closing = read_slot(api, plant.slot_id(2))
        assert closing["status"] == BuildSlotStatus.PLANNED.value
        assert closing["shift_plan_id"] is None
        assert read_shift_plan(api, plant.shift_plan_id)["committed_labor_minutes"] == 150


class TestSyncDeliveryWindowBoundary:
    """A covering dock call must still be open at the moment the slot starts."""

    def test_only_the_call_that_opens_at_the_planned_start_covers_the_module(
            self, api):
        """A call ending at the planned start covers nothing; one starting there does.

        "A **covering delivery call** for a sequenced module is one with the same
        `part_id` and the same `station_id` as the bill-of-materials line, whose
        `status` is `SCHEDULED`, `ARRIVED_ON_TIME` or `ARRIVED_LATE`, and whose window
        contains the slot's `planned_start` — that is, `window_start` at or before
        `planned_start`, and `planned_start` strictly before `window_end`."

        Design: Corner/validations/sync_delivery_window_is_inclusive_at_start_and_exclusive_at_end
        """
        plant = module_plant(api)
        module_id = plant.parts["P-MOD-1"]["id"]
        planned_slot(api, plant, 1, "2026-08-03T09:30:00Z")

        validate_error(
            api.sequence_build_slot(plant.slot_id(1), PRODUCTION_PLANNER_HEADERS),
            ApiErrorId.ERR_SYNC_DELIVERY_MISSING,
            expected_status=422,
        )

        early = new_delivery_call(api, plant.supplier_id, module_id, plant.st10_id,
                                 "2026-08-03T08:00:00Z", "2026-08-03T09:30:00Z",
                                 sequenced_qty=1)

        validate_error(
            api.sequence_build_slot(plant.slot_id(1), PRODUCTION_PLANNER_HEADERS),
            ApiErrorId.ERR_SYNC_DELIVERY_MISSING,
            expected_status=422,
        )

        # The dock pad would refuse the exact-start call while this one lives.
        assert cancel_call(api, early["id"])["status"] == \
            DeliveryCallStatus.CANCELLED.value
        exact = validate_success(
            api.create_delivery_call(
                delivery_call_payload(plant.supplier_id, module_id, plant.st10_id,
                                      "2026-08-03T09:30:00Z",
                                      "2026-08-03T10:30:00Z", sequenced_qty=1),
                PRODUCTION_PLANNER_HEADERS,
            ),
            expected_status=201,
        )

        sequenced = validate_success(
            api.sequence_build_slot(plant.slot_id(1), PRODUCTION_PLANNER_HEADERS)
        )

        assert sequenced["status"] == BuildSlotStatus.SEQUENCED.value
        assert sequenced["sync_delivery_call_id"] == exact["id"]
        assert sequenced["allocated_slot_units"] == 0
        assert read_station(api, plant.st10_id)["presentation_slots_used"] == 0
        assert read_shift_plan(api, plant.shift_plan_id)["committed_labor_minutes"] == 100


class TestChangePendingBlocksSequencing:
    """A submitted change freezes its part, and a rejection thaws it."""

    def test_sequencing_is_blocked_while_the_part_is_pending_and_resumes_on_rejection(
            self, api):
        """The block is a side effect of submission, not of approval.

        "Submission also moves the affected part `ACTIVE → CHANGE_PENDING`, and a
        `CHANGE_PENDING` part immediately blocks the sequencing of every variant whose
        effective bill of materials contains it, with `ERR_PART_CHANGE_PENDING`."

        "`REJECT` moves it `UNDER_REVIEW → REJECTED` and releases the affected part
        `CHANGE_PENDING → ACTIVE`, provided no other live change names that part."

        Design: Corner/validations/part_change_pending_blocks_sequencing_until_the_change_is_rejected
        """
        plant = base_plant_with_shift(api)
        planned_slot(api, plant, 1, "2026-08-03T07:00:00Z")
        author = make_engineering_lead_headers("eng-1")
        decider = make_engineering_lead_headers("eng-2")
        change = submitted_change(api, plant, author)

        assert change["status"] == EngineeringChangeStatus.SUBMITTED.value
        assert change["submitted_by_user_id"] == "eng-1"
        assert read_part(api, plant.part_id)["lifecycle_status"] == \
            PartLifecycleStatus.CHANGE_PENDING.value

        validate_error(
            api.sequence_build_slot(plant.slot_id(1), PRODUCTION_PLANNER_HEADERS),
            ApiErrorId.ERR_PART_CHANGE_PENDING,
            expected_status=409,
        )

        assert read_slot(api, plant.slot_id(1))["status"] == BuildSlotStatus.PLANNED.value
        validate_success(api.start_review_engineering_change(change["id"], author))

        rejected = validate_success(
            api.decide_engineering_change(
                change["id"],
                decide_payload(ChangeDecision.REJECT.value, "not needed"),
                decider,
            )
        )

        assert rejected["status"] == EngineeringChangeStatus.REJECTED.value
        assert rejected["decided_by_user_id"] == "eng-2"
        assert read_part(api, plant.part_id)["lifecycle_status"] == \
            PartLifecycleStatus.ACTIVE.value

        sequenced = validate_success(
            api.sequence_build_slot(plant.slot_id(1), PRODUCTION_PLANNER_HEADERS)
        )

        assert sequenced["status"] == BuildSlotStatus.SEQUENCED.value
        assert sequenced["allocated_slot_units"] == 2
        assert read_shift_plan(api, plant.shift_plan_id)["committed_labor_minutes"] == 150


class TestCutInPreconditionOrder:
    """Three defects in one cut-in, surfaced strictly in ladder order."""

    def test_the_stoppage_check_precedes_the_index_check_which_precedes_the_part(
            self, api):
        """Four attempts walk down the three cut-in rungs.

        "An engineering change may be cut in only while the target line's `posture` is
        `STOPPED` — otherwise `ERR_LINE_NOT_STOPPED`."

        "`cut_in_sequence_index` must be strictly greater than the target line's
        `max_released_sequence_index` — otherwise `ERR_CUT_IN_INDEX_TOO_LOW`."

        "A `replacement_part_id` must be available at cut-in and must not equal
        `affected_part_id` — otherwise `ERR_REPLACEMENT_PART_REQUIRED`."

        Design: Corner/validations/cut_in_precondition_priority_is_line_stopped_then_index_then_replacement
        """
        plant = base_plant_with_shift(api)
        released_unit(api, plant, 1)
        assert read_line(api, plant.line_id)["max_released_sequence_index"] == 1
        author = make_engineering_lead_headers("eng-1")
        decider = make_engineering_lead_headers("eng-2")
        too_low = approved_change(api, plant, author, decider,
                                  cut_in_sequence_index=1)
        no_replacement = approved_change(api, plant, author, decider,
                                         cut_in_sequence_index=5)

        validate_error(
            api.cut_in_engineering_change(too_low["id"], ENGINEERING_LEAD_HEADERS),
            ApiErrorId.ERR_LINE_NOT_STOPPED,
            expected_status=409,
        )

        stop_line(api, plant.line_id, "ENGINEERING_CHANGE")

        validate_error(
            api.cut_in_engineering_change(too_low["id"], ENGINEERING_LEAD_HEADERS),
            ApiErrorId.ERR_CUT_IN_INDEX_TOO_LOW,
            expected_status=422,
        )
        validate_error(
            api.cut_in_engineering_change(no_replacement["id"],
                                          ENGINEERING_LEAD_HEADERS),
            ApiErrorId.ERR_REPLACEMENT_PART_REQUIRED,
            expected_status=422,
        )
        validate_error(
            api.cut_in_engineering_change(
                no_replacement["id"], ENGINEERING_LEAD_HEADERS,
                {"replacement_part_id": plant.part_id},
            ),
            ApiErrorId.ERR_REPLACEMENT_PART_REQUIRED,
            expected_status=422,
        )

        for change_id in (too_low["id"], no_replacement["id"]):
            untouched = read_change(api, change_id)
            assert untouched["status"] == EngineeringChangeStatus.APPROVED.value
            assert untouched["cut_in_at"] is None
        bom = get_success_data(
            api.get_bom_line(plant.bom_lines[("WM-X", "POS-DOOR")]["id"],
                             ENGINEERING_LEAD_HEADERS)
        )
        assert bom["status"] == BomLineStatus.ACTIVE.value
        assert read_part(api, plant.part_id)["lifecycle_status"] == \
            PartLifecycleStatus.CHANGE_PENDING.value


class TestServiceObligation:
    """The legacy part outlives the change that retired it by ten years."""

    def test_the_outgoing_part_resists_obsolescence_until_a_second_past_the_deadline(
            self, api):
        """Refused before the deadline, refused at it, accepted one second later.

        "A `SERVICE_ONLY` part may not be made obsolete while the logical clock is at
        or before its `service_obligation_until` — otherwise
        `ERR_SERVICE_OBLIGATION_ACTIVE`."

        "Attempting to obsolete a part that is still `ACTIVE` or `CHANGE_PENDING` is
        refused with `ERR_INVALID_STATE`, since only the `SERVICE_ONLY → OBSOLETE`
        transition exists."

        Design: Corner/validations/service_obligation_blocks_obsolete_until_strictly_after_the_deadline
        """
        plant = base_plant(api)
        replacement = new_part(api, plant.supplier_id, "P-DOOR-B",
                               is_sequenced_module=False, line_side_max_units=24)
        plant.parts["P-DOOR-B"] = replacement
        author = make_engineering_lead_headers("eng-1")
        decider = make_engineering_lead_headers("eng-2")
        change = approved_change(api, plant, author, decider,
                                 cut_in_sequence_index=5,
                                 replacement_part_id=replacement["id"])
        stop_line(api, plant.line_id, "ENGINEERING_CHANGE")

        cut_in = validate_success(
            api.cut_in_engineering_change(change["id"], ENGINEERING_LEAD_HEADERS)
        )

        assert cut_in["status"] == EngineeringChangeStatus.CUT_IN.value
        assert same_instant(cut_in["cut_in_at"], BASE_CLOCK)
        outgoing = read_part(api, plant.part_id)
        assert outgoing["lifecycle_status"] == PartLifecycleStatus.SERVICE_ONLY.value
        assert same_instant(outgoing["service_obligation_until"],
                            "2036-08-03T06:00:00Z")

        validate_error(
            api.obsolete_part(replacement["id"], PLANT_ADMIN_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
            expected_status=409,
        )
        validate_error(
            api.obsolete_part(plant.part_id, PLANT_ADMIN_HEADERS),
            ApiErrorId.ERR_SERVICE_OBLIGATION_ACTIVE,
            expected_status=409,
        )

        set_clock(api, "2036-08-03T06:00:00Z")

        validate_error(
            api.obsolete_part(plant.part_id, PLANT_ADMIN_HEADERS),
            ApiErrorId.ERR_SERVICE_OBLIGATION_ACTIVE,
            expected_status=409,
        )

        set_clock(api, "2036-08-03T06:00:01Z")
        retired = validate_success(
            api.obsolete_part(plant.part_id, PLANT_ADMIN_HEADERS)
        )

        assert retired["lifecycle_status"] == PartLifecycleStatus.OBSOLETE.value
        assert read_part(api, replacement["id"])["lifecycle_status"] == \
            PartLifecycleStatus.ACTIVE.value


class TestHeaderChecksOutrankEverything:
    """The same malformed creation yields three different errors."""

    def test_identity_then_role_then_body_decide_the_response(self, api):
        """Nothing about the body matters until the caller is allowed in.

        "`X-User-ID` is present and non-empty, on every endpoint — otherwise
        `ERR_UNAUTHENTICATED`."

        "`X-User-Role` is one of the seven roles and appears on the endpoint's
        authorized-role list, on every endpoint — otherwise `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/validations/header_missing_x_user_id_outranks_role_and_schema_checks
        """
        set_clock(api, BASE_CLOCK)

        validate_error(
            api.create_line({}, NO_USER_ID_HEADERS),
            ApiErrorId.ERR_UNAUTHENTICATED,
            expected_status=401,
        )
        validate_error(
            api.create_line({}, LINE_OPERATOR_HEADERS),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            expected_status=403,
        )
        validate_error(
            api.create_line(line_payload("L9", takt_seconds=0), PLANT_ADMIN_HEADERS),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )
        validate_error(
            api.create_line(line_payload("L9", option_load_limit_pct=100.01),
                            PLANT_ADMIN_HEADERS),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )

        validate_error(
            api.get_line(_MISSING_LINE_ID, PLANT_ADMIN_HEADERS),
            ApiErrorId.ERR_LINE_NOT_FOUND,
            expected_status=404,
        )
        # The code is still free, so none of the four attempts persisted a line.
        survivor = validate_success(
            api.create_line(line_payload("L9"), PLANT_ADMIN_HEADERS),
            expected_status=201,
        )
        assert survivor["line_code"] == "L9"


class TestForeignKeyOrder:
    """Missing references are reported field by field, in declaration order."""

    def test_the_first_declared_missing_reference_wins_and_beats_the_version_check(
            self, api):
        """Two bogus keys report the earlier one; a bogus key beats a stale token.

        "Every foreign key carried in a request body or query string resolves to an
        existing record, checked in the order the fields are declared in that
        endpoint's input list, and reported with the referenced entity's own not-found
        code."

        "All checks are evaluated in one global ascending priority order, and the
        **first** violation encountered determines the response."

        Design: Corner/validations/fk_existence_checks_follow_the_declared_input_order
        """
        plant = base_plant(api)

        validate_error(
            api.create_build_slot(
                build_slot_payload(_MISSING_LINE_ID, _MISSING_VARIANT_ID, 1,
                                   "2026-08-03T07:00:00Z"),
                PRODUCTION_PLANNER_HEADERS,
            ),
            ApiErrorId.ERR_LINE_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            api.create_build_slot(
                build_slot_payload(plant.line_id, _MISSING_VARIANT_ID, 1,
                                   "2026-08-03T07:00:00Z"),
                PRODUCTION_PLANNER_HEADERS,
            ),
            ApiErrorId.ERR_MODEL_VARIANT_NOT_FOUND,
            expected_status=404,
        )

        stale = variant_version(api, plant.variant_id) + 40
        validate_error(
            api.create_bom_line(
                bom_line_payload(plant.variant_id, _MISSING_PART_ID, plant.st10_id,
                                 stale, "POS-LID", qty_per_unit=1),
                ENGINEERING_LEAD_HEADERS,
            ),
            ApiErrorId.ERR_PART_NOT_FOUND,
            expected_status=404,
        )

        _slots, slot_meta = validate_paginated(
            api.list_build_slots(PRODUCTION_PLANNER_HEADERS,
                                 {"line_id": plant.line_id})
        )
        assert slot_meta["total_count"] == 0
        _lines, bom_meta = validate_paginated(
            api.list_bom_lines(ENGINEERING_LEAD_HEADERS,
                               {"model_variant_id": plant.variant_id})
        )
        assert bom_meta["total_count"] == 1


class TestLaborCapacityCeiling:
    """Three harmless slots and a fourth that breaks the aggregate."""

    def test_the_fourth_slot_alone_overflows_the_shift_at_the_fatigue_tier_jump(
            self, api):
        """Committed 473 of 480 survives; the tier jump to 672 does not.

        "The covering shift plan's recomputed `committed_labor_minutes` must not exceed
        its `available_labor_minutes` when a slot is sequenced — otherwise
        `ERR_LABOR_CAPACITY_EXCEEDED`."

        Design: Corner/validations/labor_capacity_alone_rejects_the_fourth_slot_at_the_fatigue_tier_jump
        """
        plant = base_plant_with_shift(api)
        sequence_many(api, plant, [
            (1, "2026-08-03T07:00:00Z", None),
            (2, "2026-08-03T07:30:00Z", None),
            (3, "2026-08-03T08:00:00Z", None),
        ])
        planned_slot(api, plant, 4, "2026-08-03T08:30:00Z")

        inside = read_shift_plan(api, plant.shift_plan_id)
        assert inside["unit_labor_minutes"] == 450
        assert inside["committed_labor_minutes"] == 473
        assert inside["available_labor_minutes"] == 480

        validate_error(
            api.sequence_build_slot(plant.slot_id(4), PRODUCTION_PLANNER_HEADERS),
            ApiErrorId.ERR_LABOR_CAPACITY_EXCEEDED,
            expected_status=422,
        )

        refused = read_slot(api, plant.slot_id(4))
        assert refused["status"] == BuildSlotStatus.PLANNED.value
        assert refused["allocated_slot_units"] == 0
        assert read_station(api, plant.st10_id)["presentation_slots_used"] == 6
        assert read_shift_plan(api, plant.shift_plan_id)["committed_labor_minutes"] == 473
