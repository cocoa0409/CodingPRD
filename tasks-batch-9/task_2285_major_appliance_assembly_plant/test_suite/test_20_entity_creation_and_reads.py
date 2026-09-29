"""Creation shapes, seeded fields, reads, listings and rejected bodies.

Each entity is created with its declared inputs and inspected for the values the
server seeds rather than accepts, read back through its own endpoint, and probed
with a body the schema layer or an existence check has to refuse.
"""

from test_helpers import (
    LINE_OPERATOR_HEADERS,
    NON_EXISTENT_UUID,
    OMIT,
    PLANT_ADMIN_HEADERS,
    PRODUCTION_PLANNER_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
    ApiErrorId,
    BuildSlotStatus,
    LineOperatingMode,
    LinePosture,
    QualityStatus,
    QualityTestStatus,
    ShiftPlanStatus,
    SupplierStatus,
    TestResult,
    TestType,
    approx2,
    assert_identity,
    assert_line,
    assert_two_dp,
    base_plant,
    base_plant_with_shift,
    bom_line_payload,
    delivery_call_payload,
    is_valid_uuid,
    line_payload,
    line_version,
    new_line,
    new_model_variant,
    new_part,
    new_station,
    new_supplier,
    planned_slot,
    quality_test_payload,
    read_line,
    read_shift_plan,
    read_station,
    read_supplier,
    released_unit,
    set_clock,
    shift_plan_payload,
    station_payload,
    supplier_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestLineCreation:
    """A brand-new line is constrained because it has no line-side space yet."""

    def test_create_line_seeds_its_counters_and_a_constrained_posture(self, api):
        """The five declared inputs come back with ten seeded fields.

        "A newly created line comes up with `operating_mode` `RUNNING`, a null
        `stop_reason`, a `changeover_count` of 0, a `checkpoint_index` of 0, a
        `max_released_sequence_index` of 0, `presentation_slots_total` and
        `presentation_slots_committed` both 0, a `free_slot_pct` of 0.00 and
        therefore — per §2.10 — a `posture` of `CONSTRAINED`."

        Design: Corner/entities/create_line_returns_declared_fields_with_initial_posture_constrained
        """
        set_clock(api, "2026-08-03T06:00:00Z")

        line = validate_success(
            api.create_line(line_payload("L1"), PLANT_ADMIN_HEADERS),
            expected_status=201,
        )

        assert_line(line)
        assert line["line_code"] == "L1"
        assert line["takt_seconds"] == 120
        assert float(line["option_load_limit_pct"]) == approx2(63.00)
        assert line["baseline_headcount"] == 20
        assert line["current_family_code"] == "FAM_A"
        assert line["operating_mode"] == LineOperatingMode.RUNNING.value
        assert line["stop_reason"] is None
        assert line["changeover_count"] == 0
        assert line["checkpoint_index"] == 0
        assert line["max_released_sequence_index"] == 0
        assert line["presentation_slots_total"] == 0
        assert line["presentation_slots_committed"] == 0
        assert float(line["free_slot_pct"]) == approx2(0.00)
        assert line["posture"] == LinePosture.CONSTRAINED.value
        assert line["version"] == 1


class TestStationCreation:
    """The used counter is the server's to keep, not the client's to set."""

    def test_a_client_supplied_slots_used_is_ignored_and_the_line_reopens(self, api):
        """The station starts empty and its capacity flows up to the line.

        "A station begins with `presentation_slots_used` at 0. Creating a station
        immediately re-derives the line's `presentation_slots_total`, `free_slot_pct`
        and `posture`, and advances the line's `version`."

        Design: Corner/entities/station_presentation_slots_used_computed_input_ignored
        """
        set_clock(api, "2026-08-03T06:00:00Z")
        line = new_line(api, "L1")

        station = validate_success(
            api.create_station(
                station_payload(line["id"], "ST30", 30, presentation_slots_used=7),
                PLANT_ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        assert station["presentation_slots_used"] == 0
        assert station["presentation_slot_capacity"] == 40
        assert station["position_index"] == 30
        reopened = read_line(api, line["id"])
        assert reopened["presentation_slots_total"] == 40
        assert reopened["presentation_slots_committed"] == 0
        assert float(reopened["free_slot_pct"]) == approx2(100.00)
        assert reopened["posture"] == LinePosture.OPEN.value
        assert reopened["version"] == 2


class TestSupplierCreation:
    """A supplier's standing is replayed from counters, never supplied."""

    def test_a_client_supplied_score_status_and_counters_are_ignored(self, api):
        """An optimistic body cannot buy a reputation.

        "A new supplier starts `APPROVED` with an `on_time_score` of 100.00 and with
        `delivered_on_time_count`, `delivered_late_count`, `missed_count` and
        `quality_penalty_count` all at zero."

        Design: Corner/entities/create_supplier_score_and_counters_ignored_input
        """
        set_clock(api, "2026-08-03T06:00:00Z")

        supplier = validate_success(
            api.create_supplier(
                supplier_payload("SUP9", "Optimistic Modules AB",
                                 on_time_score=12.00, status="SUSPENDED",
                                 missed_count=9),
                PLANT_ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        assert float(supplier["on_time_score"]) == approx2(100.00)
        assert supplier["status"] == SupplierStatus.APPROVED.value
        assert supplier["delivered_on_time_count"] == 0
        assert supplier["delivered_late_count"] == 0
        assert supplier["missed_count"] == 0
        assert supplier["quality_penalty_count"] == 0
        assert supplier["supplier_code"] == "SUP9"
        assert supplier["sync_window_minutes"] == 30
        assert supplier["version"] == 1
        assert is_valid_uuid(supplier["id"])


class TestShiftPlanCreationAndRead:
    """Overtime defaults to nothing, is capped at two hours, and reads back."""

    def _line_with_two_stations(self, api):
        set_clock(api, "2026-08-03T06:00:00Z")
        line = new_line(api, "L1")
        new_station(api, line["id"], "ST10", 10)
        new_station(api, line["id"], "ST20", 20)
        return line

    def test_read_returns_the_stored_window_with_its_computed_capacity(self, api):
        """Four hundred and eighty minutes are available and none committed.

        "`available_labor_minutes` is the shift's 480 base minutes plus its
        `overtime_minutes`; the line runs a single crew, so `planned_headcount` is
        emphatically **not** a factor in available minutes — its only role in this
        system is to scale the option-load window cap of §3.5."

        Design: Corner/entities/get_shift_plan_returns_stored_window_and_capacity
        """
        line = self._line_with_two_stations(api)
        version_before = line_version(api, line["id"])
        created = validate_success(
            api.create_shift_plan(
                shift_plan_payload(line["id"], version_before),
                PRODUCTION_PLANNER_HEADERS,
            ),
            expected_status=201,
        )

        plan = validate_success(
            api.get_shift_plan(created["id"], LINE_OPERATOR_HEADERS)
        )

        assert plan["line_id"] == line["id"]
        assert plan["shift_date"] == "2026-08-03"
        assert plan["shift_code"] == "A"
        assert plan["planned_headcount"] == 20
        assert plan["overtime_minutes"] == 0
        assert plan["available_labor_minutes"] == 480
        assert plan["unit_labor_minutes"] == 0
        assert plan["changeover_minutes"] == 0
        assert plan["committed_labor_minutes"] == 0
        assert plan["status"] == ShiftPlanStatus.ACTIVE.value
        assert plan["version"] == 1
        assert line_version(api, line["id"]) == version_before + 1

    def test_omitting_overtime_minutes_stores_zero(self, api):
        """The optional field defaults and the stored end is not stretched.

        "A production planner or plant administrator creates a plan for a line by
        supplying the `line_id`, the `shift_date` as a `YYYY-MM-DD` calendar date in
        UTC, the `shift_code`, a `planned_headcount` of at least 1, the absolute
        `shift_start` and `shift_end` instants, the mandatory `expected_line_version`
        of §2.7, and optionally `overtime_minutes` between 0 and 120 inclusive
        (defaulting to 0)."

        Design: Corner/entities/create_shift_plan_omitting_overtime_minutes_defaults_to_zero
        """
        line = self._line_with_two_stations(api)

        plan = validate_success(
            api.create_shift_plan(
                shift_plan_payload(line["id"], line_version(api, line["id"]),
                                   shift_code="B", planned_headcount=18,
                                   shift_start="2026-08-03T14:00:00Z",
                                   shift_end="2026-08-03T22:00:00Z"),
                PRODUCTION_PLANNER_HEADERS,
            ),
            expected_status=201,
        )

        assert plan["overtime_minutes"] == 0
        assert plan["available_labor_minutes"] == 480
        assert plan["committed_labor_minutes"] == 0
        assert plan["planned_headcount"] == 18

    def test_overtime_above_two_hours_is_a_schema_rejection(self, api):
        """One hundred and twenty minutes are legal and 121 are not.

        "Body and query shape, on every endpoint: required fields present, types
        correct, enum members recognized, numeric bounds honoured (`takt_seconds` at
        least 1; `option_load_limit_pct` greater than 0 and at most 100;
        `qty_per_unit` at least 1; `option_content_points` between 0 and 10
        inclusive; `overtime_minutes` between 0 and 120 inclusive; `sequence_index`
        at least 1; `limit` between 1 and 100 inclusive; `offset` not negative),
        timestamps well-formed ISO 8601, `window_start` strictly before `window_end`,
        and `shift_start` strictly before `shift_end`."

        Design: Corner/entities/create_shift_plan_overtime_above_cap_rejected
        """
        line = self._line_with_two_stations(api)
        version_before = line_version(api, line["id"])

        validate_error(
            api.create_shift_plan(
                shift_plan_payload(line["id"], version_before,
                                   overtime_minutes=121),
                PRODUCTION_PLANNER_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )

        # A schema rejection does not consume the concurrency token.
        assert line_version(api, line["id"]) == version_before
        accepted = validate_success(
            api.create_shift_plan(
                shift_plan_payload(line["id"], version_before,
                                   overtime_minutes=120),
                PRODUCTION_PLANNER_HEADERS,
            ),
            expected_status=201,
        )
        assert accepted["overtime_minutes"] == 120
        assert accepted["available_labor_minutes"] == 600
        _rows, meta = validate_paginated(
            api.list_line_shift_plans(line["id"], PRODUCTION_PLANNER_HEADERS)
        )
        assert meta["total_count"] == 1


class TestBuildSlotListingAndCreation:
    """Build slots page in sequence order and reserve nothing when refused."""

    def test_the_list_pages_in_sequence_index_order_with_a_filtered_total(self, api):
        """Two slots, one per page, in ascending index order.

        "Every list response repeats `limit` and `offset` in the `meta` object
        alongside `total_count` (the number of records matching the filters before
        pagination) and `has_more` (true when records remain beyond the current
        page)."

        Design: Corner/entities/list_build_slots_returns_pagination_envelope_in_sequence_order
        """
        plant = base_plant(api)
        planned_slot(api, plant, 1, "2026-08-03T07:00:00Z")
        planned_slot(api, plant, 2, "2026-08-03T07:30:00Z")

        first_rows, first_meta = validate_paginated(
            api.list_build_slots(PRODUCTION_PLANNER_HEADERS,
                                 {"line_id": plant.line_id, "limit": 1, "offset": 0})
        )
        second_rows, second_meta = validate_paginated(
            api.list_build_slots(PRODUCTION_PLANNER_HEADERS,
                                 {"line_id": plant.line_id, "limit": 1, "offset": 1})
        )

        assert len(first_rows) == 1
        assert first_rows[0]["id"] == plant.slot_id(1)
        assert first_rows[0]["sequence_index"] == 1
        assert first_meta["total_count"] == 2
        assert first_meta["limit"] == 1
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True
        assert len(second_rows) == 1
        assert second_rows[0]["id"] == plant.slot_id(2)
        assert second_rows[0]["sequence_index"] == 2
        assert second_meta["total_count"] == 2
        assert second_meta["offset"] == 1
        assert second_meta["has_more"] is False

    def test_an_unknown_line_is_refused_and_leaves_the_index_available(self, api):
        """The parent is resolved before anything is reserved.

        "Every foreign key carried in a request body or query string resolves to an
        existing record, checked in the order the fields are declared in that
        endpoint's input list, and reported with the referenced entity's own
        not-found code."

        Design: Corner/entities/create_build_slot_unknown_line_not_found
        """
        plant = base_plant(api)

        validate_error(
            api.create_build_slot(
                {"line_id": NON_EXISTENT_UUID,
                 "model_variant_id": plant.variant_id,
                 "sequence_index": 1,
                 "planned_start": "2026-08-03T07:00:00Z"},
                PRODUCTION_PLANNER_HEADERS,
            ),
            ApiErrorId.ERR_LINE_NOT_FOUND,
            expected_status=404,
        )

        slot = validate_success(
            api.create_build_slot(
                {"line_id": plant.line_id,
                 "model_variant_id": plant.variant_id,
                 "sequence_index": 1,
                 "planned_start": "2026-08-03T07:00:00Z"},
                PRODUCTION_PLANNER_HEADERS,
            ),
            expected_status=201,
        )
        assert slot["sequence_index"] == 1
        assert slot["status"] == BuildSlotStatus.PLANNED.value
        _rows, meta = validate_paginated(
            api.list_build_slots(PRODUCTION_PLANNER_HEADERS,
                                 {"line_id": plant.line_id})
        )
        assert meta["total_count"] == 1


class TestNotFoundAndBodyRejections:
    """Unknown ids and malformed bodies never leave a trace."""

    def test_an_unknown_production_unit_id_is_a_typed_not_found(self, api):
        """The path parameter is resolved against the endpoint's own type.

        "The `{id}` path parameter resolves to an entity of the endpoint's own type,
        on every endpoint carrying one, and the failure carries that entity's own
        not-found code: `ERR_LINE_NOT_FOUND`, `ERR_STATION_NOT_FOUND`,
        `ERR_MODEL_VARIANT_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`,
        `ERR_PART_NOT_FOUND`, `ERR_BOM_LINE_NOT_FOUND`,
        `ERR_DELIVERY_CALL_NOT_FOUND`, `ERR_SHIFT_PLAN_NOT_FOUND`,
        `ERR_BUILD_SLOT_NOT_FOUND`, `ERR_PRODUCTION_UNIT_NOT_FOUND`,
        `ERR_ENGINEERING_CHANGE_NOT_FOUND` or `ERR_WARRANTY_RETURN_NOT_FOUND`."

        Design: Corner/entities/get_production_unit_unknown_id_not_found
        """
        set_clock(api, "2026-08-03T06:00:00Z")

        validate_error(
            api.get_production_unit(NON_EXISTENT_UUID, QUALITY_INSPECTOR_HEADERS),
            ApiErrorId.ERR_PRODUCTION_UNIT_NOT_FOUND,
            expected_status=404,
        )

        # The same 404 answers every role the read is open to.
        validate_error(
            api.get_production_unit(NON_EXISTENT_UUID, PLANT_ADMIN_HEADERS),
            ApiErrorId.ERR_PRODUCTION_UNIT_NOT_FOUND,
            expected_status=404,
        )

    def test_a_delivery_call_without_a_sequenced_qty_is_refused(self, api):
        """The quantity is a declared input, so its absence is a bad request.

        "A production planner or plant administrator books a **delivery call** by
        supplying the `supplier_id` called off, the `part_id` or sequenced module
        wanted, the `station_id` that serves as the line-side drop point, a
        `window_start` and a `window_end` bounding the delivery window, and a
        `sequenced_qty` of at least 1 counting the modules in the drop."

        Design: Corner/entities/create_delivery_call_missing_required_sequenced_qty_rejected
        """
        set_clock(api, "2026-08-03T06:00:00Z")
        line = new_line(api, "L1")
        station = new_station(api, line["id"], "ST10", 10)
        supplier = new_supplier(api, "SUP1", "Hinge and Module Co")
        part = new_part(api, supplier["id"], "P-DOOR-A")

        validate_error(
            api.create_delivery_call(
                delivery_call_payload(supplier["id"], part["id"], station["id"],
                                      sequenced_qty=OMIT),
                PRODUCTION_PLANNER_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )

        _rows, meta = validate_paginated(
            api.list_delivery_calls(PRODUCTION_PLANNER_HEADERS,
                                    {"station_id": station["id"]})
        )
        assert meta["total_count"] == 0
        untouched = read_supplier(api, supplier["id"])
        assert float(untouched["on_time_score"]) == approx2(100.00)
        assert untouched["delivered_on_time_count"] == 0

    def test_an_unknown_part_outranks_the_stale_variant_token(self, api):
        """Existence is checked before concurrency, so 404 wins over 412.

        "Every foreign key carried in a request body or query string resolves to an
        existing record, checked in the order the fields are declared in that
        endpoint's input list, and reported with the referenced entity's own
        not-found code."

        Design: Corner/entities/create_bom_line_unknown_part_not_found
        """
        set_clock(api, "2026-08-03T06:00:00Z")
        line = new_line(api, "L1")
        station = new_station(api, line["id"], "ST10", 10)
        variant = new_model_variant(api, "WM-X", "FAM_A")

        validate_error(
            api.create_bom_line(
                bom_line_payload(variant["id"], NON_EXISTENT_UUID, station["id"],
                                 variant["version"] + 98),
                PLANT_ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_PART_NOT_FOUND,
            expected_status=404,
        )

        _rows, meta = validate_paginated(
            api.list_bom_lines(PLANT_ADMIN_HEADERS,
                               {"model_variant_id": variant["id"]})
        )
        assert meta["total_count"] == 0
        assert validate_success(
            api.get_model_variant(variant["id"], PLANT_ADMIN_HEADERS)
        )["version"] == 1


class TestQualityTestIsAppendOnly:
    """A measurement carries no version and no update pathway."""

    def test_a_recorded_measurement_has_no_version_and_no_updated_at(self, api):
        """The one entity that is a bare record of a reading.

        "A quality test is an append-only measurement record: it carries `id` and
        `created_at` only. It has **no** `updated_at` and **no** `version`, and no
        client-facing endpoint updates one."

        Design: Corner/entities/quality_test_is_immutable_with_no_version_field
        """
        plant = base_plant_with_shift(api)
        unit = released_unit(api, plant, 1)
        recorded = validate_success(
            api.record_quality_test(
                unit["id"],
                quality_test_payload(TestType.ELECTRICAL_SAFETY.value, 0.30),
                QUALITY_INSPECTOR_HEADERS,
            ),
            expected_status=201,
        )

        rows, meta = validate_paginated(
            api.list_quality_tests(unit["id"], QUALITY_INSPECTOR_HEADERS)
        )

        assert meta["total_count"] == 1
        test = rows[0]
        assert test["id"] == recorded["id"]
        assert test["production_unit_id"] == unit["id"]
        assert test["test_type"] == TestType.ELECTRICAL_SAFETY.value
        assert float(test["measured_value"]) == approx2(0.30)
        assert float(test["limit_value"]) == approx2(0.50)
        assert test["result"] == TestResult.PASS.value
        assert test["status"] == QualityTestStatus.RECORDED.value
        assert_identity(test)
        assert_two_dp(test["measured_value"], "measured_value")
        assert "version" not in test
        assert "updated_at" not in test
        # Recording a passing safety measurement is all that moved on the unit.
        assert validate_success(
            api.get_production_unit(unit["id"], QUALITY_INSPECTOR_HEADERS)
        )["quality_status"] == QualityStatus.SAFETY_PASSED.value
        assert read_station(api, plant.st10_id)["presentation_slots_used"] == 2
        assert read_shift_plan(api, plant.shift_plan_id)["committed_labor_minutes"] == 150
