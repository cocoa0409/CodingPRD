"""Dyno testing (thresholds, cell scheduling, immutable records) and the
quality seal (state gate, segregation of duties, work-order bubble-up)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_work_order,
    assert_dyno_test,
    assert_reman_engine,
    build_engine_in_dyno_test,
    create_active_spec,
    create_distributor,
    get_reman_engine,
    get_work_order,
    list_operations,
    make_quality_inspector_headers,
    make_shop_technician_headers,
    record_dyno_test,
    record_dyno_test_payload,
    seal_engine,
    set_logical_clock,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
)

ADMIN = TEST_USERS["plant_admin_headers"]
TECH = TEST_USERS["shop_technician_headers"]
QUALITY = TEST_USERS["quality_inspector_headers"]


def _engine_in_dyno_test(api, slot=0, app_code="SUBURBAN-1996"):
    distributor = create_distributor(distributor_code=f"D-DYNO-{app_code}",
                                     name="Dyno Cores")
    spec = create_active_spec(application_code=app_code)
    return build_engine_in_dyno_test(spec, distributor, slot=slot)


class TestDynoResultThreshold:
    def test_oil_pressure_below_minimum_fails(self, api):
        """PRD §3.8: "The test's `result` is computed, not supplied: `PASS`
        when the measured `horsepower` is at least the spec's
        `dyno_min_horsepower` and the measured `oil_pressure_psi` is at least
        the spec's `dyno_min_oil_pressure_psi` and the measured
        `coolant_temp_f` is no more than the spec's `dyno_max_coolant_temp_f`;
        otherwise `FAIL`."
        PRD §3.8: "A `FAIL` leaves the engine in `BUILT` and sets
        `latest_dyno_result` to `FAIL`".

        Design: Difficulty/boundary_precision_check/dyno_oil_pressure_threshold_equality
        """
        set_logical_clock()
        ctx = _engine_in_dyno_test(api)

        test = record_dyno_test(ctx["engine"]["id"], ctx["dyno_cell_code"],
                                slot=0, oil_pressure_psi=19.9)
        assert_dyno_test(test)
        assert test["result"] == "FAIL", "19.9 < 20.0 minimum oil pressure"

        engine = get_reman_engine(ctx["engine"]["id"])
        assert engine["status"] == "BUILT", "a failed dyno does not advance"
        assert engine["latest_dyno_result"] == "FAIL"

    def test_oil_pressure_at_minimum_passes(self, api):
        """PRD §3.8: "`PASS` when the measured `horsepower` is at least the
        spec's `dyno_min_horsepower` and the measured `oil_pressure_psi` is at
        least the spec's `dyno_min_oil_pressure_psi`".
        PRD §3.8: "A `PASS` moves the engine from `BUILT` to `DYNO_PASSED`."
        PRD §3.8: "The system stamps each record with `recorded_by` (the
        recording technician's `X-User-ID`) and a 1-based `attempt` counter
        over the engine's tests".

        Design: Difficulty/boundary_precision_check/dyno_oil_pressure_threshold_equality
        """
        set_logical_clock()
        ctx = _engine_in_dyno_test(api)
        record_dyno_test(ctx["engine"]["id"], ctx["dyno_cell_code"],
                         slot=0, oil_pressure_psi=19.9)

        test2 = record_dyno_test(ctx["engine"]["id"], ctx["dyno_cell_code"],
                                 slot=1, oil_pressure_psi=20.0)
        assert test2["result"] == "PASS", "20.0 >= 20.0: inclusive threshold"
        assert test2["attempt"] == 2
        assert test2["recorded_by"] == "tech-1"

        engine = get_reman_engine(ctx["engine"]["id"])
        assert engine["status"] == "DYNO_PASSED"
        assert engine["latest_dyno_result"] == "PASS"


class TestDynoCellScheduling:
    def test_dyno_cell_start_at_prior_end_conflicts(self, api):
        """PRD §3.8: "The dyno cell is a scheduled resource with a cooldown
        buffer: each recorded test occupies the cell from its `started_at`
        until thirty minutes after its `ended_at`."
        PRD §3.8: "A new test on the same `dyno_cell_code` conflicts whenever
        its buffer-extended interval intersects another test's buffer-extended
        interval — and because the buffers extend the ends, a new test
        starting exactly at a prior test's `ended_at` still conflicts."
        PRD §3.8: "Such a conflict is rejected with
        `ERR_DYNO_CELL_SCHEDULE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/dyno_cell_cooldown_buffer_overlap
        """
        set_logical_clock()
        ctx1 = _engine_in_dyno_test(api, slot=0, app_code="TAHOE-1999")
        record_dyno_test(ctx1["engine"]["id"], "CELL-BUF",
                         started_at="2026-08-03T10:00:00Z",
                         ended_at="2026-08-03T11:00:00Z")
        # Same spec -> second engine via a second core from the same supplier.
        ctx2 = build_engine_in_dyno_test(ctx1["spec"], ctx1["core_distributor"],
                                         slot=1)

        resp = api.record_dyno_test(
            ctx2["engine"]["id"],
            record_dyno_test_payload("CELL-BUF", "2026-08-03T11:00:00Z",
                                     "2026-08-03T12:00:00Z"),
            TECH)
        validate_error(resp, ApiErrorId.ERR_DYNO_CELL_SCHEDULE_OVERLAP)

        engine2 = get_reman_engine(ctx2["engine"]["id"])
        assert engine2["latest_dyno_result"] is None, (
            "the rejected test left no record")
        tests, meta = validate_paginated(
            api.list_dyno_tests(ctx2["engine"]["id"], ADMIN))
        assert tests == [] and meta["total_count"] == 0

    def test_dyno_cell_start_at_end_plus_buffer_allowed(self, api):
        """PRD §3.8: "each recorded test occupies the cell from its
        `started_at` until thirty minutes after its `ended_at`."
        PRD §3.8: "The system stamps each record with `recorded_by` (the
        recording technician's `X-User-ID`) and a 1-based `attempt` counter
        over the engine's tests".

        Design: Difficulty/resource_temporal_overlap/dyno_cell_cooldown_buffer_overlap
        """
        set_logical_clock()
        ctx1 = _engine_in_dyno_test(api, slot=0, app_code="TAHOE-1999")
        record_dyno_test(ctx1["engine"]["id"], "CELL-BUF",
                         started_at="2026-08-03T10:00:00Z",
                         ended_at="2026-08-03T11:00:00Z")
        ctx2 = build_engine_in_dyno_test(ctx1["spec"], ctx1["core_distributor"],
                                         slot=1)

        # Prior occupation is [10:00, 11:30); starting at 11:30 is free.
        test = record_dyno_test(ctx2["engine"]["id"], "CELL-BUF",
                                started_at="2026-08-03T11:30:00Z",
                                ended_at="2026-08-03T12:30:00Z")
        assert test["result"] == "PASS"
        assert test["attempt"] == 1

        tests, meta = validate_paginated(
            api.list_dyno_tests(ctx2["engine"]["id"], ADMIN))
        assert len(tests) == 1 and meta["total_count"] == 1


class TestDynoRecordShape:
    def test_dyno_test_record_is_immutable(self, api):
        """PRD §2.4: "`DynoTest` records are the single exception: they are
        immutable once written, and therefore carry only `id` and
        `created_at`."
        PRD §2.4: "Both `updated_at` and `version` are absent from a
        `DynoTest`."

        Design: Corner/entities/dyno_test_record_is_immutable
        """
        set_logical_clock()
        ctx = _engine_in_dyno_test(api, app_code="LUMINA-1996")
        test = record_dyno_test(ctx["engine"]["id"], "CELL-IMM", slot=0)
        assert test["result"] == "PASS"
        assert_dyno_test(test)  # id + created_at; no updated_at / version

        listed, _meta = validate_paginated(
            api.list_dyno_tests(ctx["engine"]["id"], ADMIN))
        assert len(listed) == 1
        assert_dyno_test(listed[0])


class TestSealGates:
    def test_seal_without_any_dyno_test_rejected(self, api):
        """PRD §3.8: "The quality gate doubles as the seal's state gate: the
        engine's `latest_dyno_result` must be `PASS` — equivalently, the
        engine must stand in `DYNO_PASSED`, which is reachable only via a
        passing dyno — and any seal attempt on an engine that is `BUILT`,
        untested, or whose latest test failed is reported as
        `ERR_DYNO_NOT_PASSED` (HTTP 422), not as a generic state error."

        Design: Difficulty/cross_entity_state_dependency/seal_requires_latest_dyno_pass
        """
        set_logical_clock()
        ctx = _engine_in_dyno_test(api, app_code="SILVERADO-1998")
        engine = get_reman_engine(ctx["engine"]["id"])
        assert engine["status"] == "BUILT"
        assert engine["latest_dyno_result"] is None, "never tested"

        resp = api.seal_reman_engine(ctx["engine"]["id"], QUALITY)
        validate_error(resp, ApiErrorId.ERR_DYNO_NOT_PASSED)
        assert get_reman_engine(ctx["engine"]["id"])["status"] == "BUILT"

    def test_seal_after_failed_dyno_rejected_then_pass_seals(self, api):
        """PRD §3.8: "any seal attempt on an engine that is `BUILT`,
        untested, or whose latest test failed is reported as
        `ERR_DYNO_NOT_PASSED` (HTTP 422), not as a generic state error."
        PRD §3.8: "A successful seal moves the engine from `DYNO_PASSED` to
        `SEALED`, stamping `sealed_at` from the logical clock and `sealed_by`
        with the inspector's `X-User-ID`, and bubbles up: the parent work
        order — the one named by the engine's `work_order_id` — moves from
        `DYNO_TEST` to `CLOSED`, incrementing its `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/seal_requires_latest_dyno_pass
        """
        set_logical_clock()
        ctx = _engine_in_dyno_test(api, app_code="SILVERADO-1998")
        record_dyno_test(ctx["engine"]["id"], ctx["dyno_cell_code"], slot=0,
                         horsepower=250)  # 250 < 300 -> FAIL

        resp = api.seal_reman_engine(ctx["engine"]["id"], QUALITY)
        validate_error(resp, ApiErrorId.ERR_DYNO_NOT_PASSED)

        record_dyno_test(ctx["engine"]["id"], ctx["dyno_cell_code"], slot=1)
        sealed = seal_engine(ctx["engine"]["id"], qi_user_id="qi-1")
        assert_reman_engine(sealed)
        assert sealed["status"] == "SEALED"
        assert sealed["sealed_by"] == "qi-1"
        assert sealed["sealed_at"] is not None

        wo = get_work_order(ctx["work_order"]["id"])
        assert wo["status"] == "CLOSED", "seal bubbles up to the work order"

    def test_seal_by_dyno_recorder_forbidden(self, api):
        """PRD §3.8: "Then segregation of duties: the sealing inspector's
        `X-User-ID` must differ from the `recorded_by` of the engine's most
        recent dyno test, else `ERR_SEALER_IS_TESTER` (HTTP 403)."

        Design: Corner/validations/seal_by_dyno_recorder_forbidden
        """
        set_logical_clock()
        ctx = _engine_in_dyno_test(api, app_code="BLAZER-1994")
        record_dyno_test(ctx["engine"]["id"], ctx["dyno_cell_code"], slot=0,
                         tech_user_id="tech-1")

        resp = api.seal_reman_engine(ctx["engine"]["id"],
                                     make_quality_inspector_headers("tech-1"))
        validate_error(resp, ApiErrorId.ERR_SEALER_IS_TESTER)
        assert get_reman_engine(ctx["engine"]["id"])["status"] == "DYNO_PASSED"

        sealed = seal_engine(ctx["engine"]["id"], qi_user_id="qi-7")
        assert sealed["status"] == "SEALED"
        assert sealed["sealed_by"] == "qi-7"

    def test_seal_as_shop_technician_forbidden(self, api):
        """PRD §2.1: "Access to each operation is restricted by role; a caller
        whose role is not listed for the endpoint will be rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §3.8: "Sealing is the quality gate that turns a tested engine into
        sellable stock, performed by a `QualityInspector`."

        Design: Corner/rbac/seal_as_shop_technician_forbidden
        """
        set_logical_clock()
        ctx = _engine_in_dyno_test(api, app_code="JIMMY-1995")
        record_dyno_test(ctx["engine"]["id"], ctx["dyno_cell_code"], slot=0)

        resp = api.seal_reman_engine(ctx["engine"]["id"],
                                     make_shop_technician_headers("tech-2"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_reman_engine(ctx["engine"]["id"])["status"] == "DYNO_PASSED"

    def test_double_seal_rejected_idempotency(self, api):
        """PRD §3.8: "A successful seal moves the engine from `DYNO_PASSED` to
        `SEALED`, stamping `sealed_at` from the logical clock and `sealed_by`
        with the inspector's `X-User-ID`".
        PRD §3.8: "The quality gate doubles as the seal's state gate: the
        engine's `latest_dyno_result` must be `PASS` — equivalently, the
        engine must stand in `DYNO_PASSED`, which is reachable only via a
        passing dyno".

        Design: Corner/state_machines/double_seal_rejected_idempotency
        """
        set_logical_clock()
        ctx = _engine_in_dyno_test(api, app_code="BRAVADA-1996")
        record_dyno_test(ctx["engine"]["id"], ctx["dyno_cell_code"], slot=0)
        first = seal_engine(ctx["engine"]["id"], qi_user_id="qi-1")
        assert first["status"] == "SEALED"

        # A SEALED engine is no longer in the seal from-state; the rejection
        # may surface from the seal's quality/state gate or the generic
        # state-transition gate.
        resp = api.seal_reman_engine(
            ctx["engine"]["id"], make_quality_inspector_headers("qi-2"))
        validate_error_is_one_of(resp, [ApiErrorId.ERR_DYNO_NOT_PASSED,
                                        ApiErrorId.ERR_INVALID_STATE])

        after = get_reman_engine(ctx["engine"]["id"])
        assert after["status"] == "SEALED"
        assert after["sealed_by"] == "qi-1", "the first seal stands"
        assert after["sealed_at"] == first["sealed_at"]


class TestDynoReworkLoop:
    def test_rework_loop_resets_to_machining_without_reminting_engine(self, api):
        """PRD §3.8: "advancing from `DYNO_TEST` back to `MACHINING` is
        permitted only when the referenced engine's `latest_dyno_result` is
        `FAIL`."
        PRD §3.8: "Taking the rework loop increments the work order's
        `rework_count` by 1 and resets every `FAILED` machining operation on
        the order back to `PENDING` with its stored window fields cleared".
        PRD §3.5: "The first entry into `ASSEMBLY` is also the moment the
        engine is born: if `reman_engine_id` is still null, the system creates
        the `RemanEngine` — copying `build_spec_id` from the work order,
        minting its `serial_number`, and setting its initial `status` to
        `BUILT` — and links it onto the work order."

        Design: Difficulty/non_linear_state_machine/work_order_dyno_rework_loop
        """
        set_logical_clock()
        ctx = _engine_in_dyno_test(api, slot=0, app_code="BLAZER-1995")
        engine_id = ctx["engine"]["id"]
        wo_id = ctx["work_order"]["id"]

        fail = record_dyno_test(engine_id, ctx["dyno_cell_code"], slot=0,
                                horsepower=250)  # 250 < 300 -> FAIL
        assert fail["result"] == "FAIL"
        mid = get_reman_engine(engine_id)
        assert mid["status"] == "BUILT" and mid["latest_dyno_result"] == "FAIL"

        wo_before = get_work_order(wo_id)
        reworked = advance_work_order(wo_id, "MACHINING")
        assert reworked["status"] == "MACHINING"
        assert reworked["rework_count"] == 1
        assert reworked["version"] == wo_before["version"] + 1

        ops = list_operations(wo_id)
        assert ops[0]["status"] == "COMPLETED", (
            "only FAILED operations reset; the COMPLETED op keeps its window")
        assert ops[0]["station_code"] is not None

        wo2 = advance_work_order(wo_id, "ASSEMBLY")
        assert wo2["reman_engine_id"] == engine_id, (
            "re-entering ASSEMBLY must not mint a second engine")
        advance_work_order(wo_id, "DYNO_TEST")
        record_dyno_test(engine_id, ctx["dyno_cell_code"], slot=1)  # PASS
        seal_engine(engine_id, qi_user_id="qi-1")

        assert get_reman_engine(engine_id)["status"] == "SEALED"
        assert get_work_order(wo_id)["status"] == "CLOSED"

    def test_rework_loop_second_dyno_passes_with_incremented_attempt(self, api):
        """PRD §3.8: "A `FAIL` leaves the engine in `BUILT` and sets
        `latest_dyno_result` to `FAIL`, which is exactly the condition that
        makes the parent work order eligible for the rework loop".
        PRD §3.8: "The system stamps each record with `recorded_by` (the
        recording technician's `X-User-ID`) and a 1-based `attempt` counter
        over the engine's tests, and refreshes the engine's
        `latest_dyno_result` to the `result` of the most recent test by
        creation time — null if the engine has never been tested."

        Design: Difficulty/non_linear_state_machine/work_order_dyno_rework_loop
        """
        set_logical_clock()
        ctx = _engine_in_dyno_test(api, slot=0, app_code="BLAZER-1995")
        engine_id = ctx["engine"]["id"]
        wo_id = ctx["work_order"]["id"]

        record_dyno_test(engine_id, ctx["dyno_cell_code"], slot=0,
                         horsepower=250)
        reworked = advance_work_order(wo_id, "MACHINING")
        assert reworked["rework_count"] == 1

        advance_work_order(wo_id, "ASSEMBLY")
        advance_work_order(wo_id, "DYNO_TEST")
        second = record_dyno_test(engine_id, ctx["dyno_cell_code"], slot=1)
        assert second["result"] == "PASS"
        assert second["attempt"] == 2, (
            "the attempt counter spans the rework loop on the same engine")

        engine = get_reman_engine(engine_id)
        assert engine["status"] == "DYNO_PASSED"
        assert engine["latest_dyno_result"] == "PASS"
