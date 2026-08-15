"""Machining route declaration (OCC-guarded) and station scheduling."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_work_order,
    create_active_spec,
    create_distributor,
    create_graded_return,
    declare_operation_payload,
    declare_route,
    get_work_order,
    list_operations,
    open_work_order,
    perform_operation,
    perform_operation_payload,
    record_dyno_test_payload,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["plant_admin_headers"]
TECH = TEST_USERS["shop_technician_headers"]


def _wo_in_machining_with_pending_op(distributor, spec):
    """GRADED return -> work order -> TEARDOWN -> route declared -> MACHINING.
    Returns (work_order_id, first pending operation)."""
    ret = create_graded_return(distributor, spec)
    wo = open_work_order(ret)
    wo = advance_work_order(wo["id"], "TEARDOWN")
    ops = declare_route(wo, spec)
    advance_work_order(wo["id"], "MACHINING")
    return wo["id"], ops[0]


class TestRouteSequence:
    def test_route_sequence_enforced_on_perform(self, api):
        """PRD §3.6: "Second, route order: every operation of the same work
        order with a smaller `sequence` must already be `COMPLETED`;
        performing out of order is rejected with
        `ERR_ROUTE_SEQUENCE_VIOLATION` (HTTP 422)."

        Design: Corner/state_machines/route_sequence_enforced_on_perform
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-SEQ",
                                         name="Sequence Cores")
        spec = create_active_spec(application_code="C1500-1995",
                                  required_op_sequence=["CRANK_GRIND", "BORE"])
        ret = create_graded_return(distributor, spec)
        wo = open_work_order(ret)
        wo = advance_work_order(wo["id"], "TEARDOWN")
        ops = declare_route(wo, spec)  # CRANK_GRIND seq 1, BORE seq 2
        advance_work_order(wo["id"], "MACHINING")
        op1, op2 = ops[0], ops[1]

        resp = api.perform_operation(
            op2["id"],
            perform_operation_payload("STN-BORE-1", "2026-08-02T08:00:00Z",
                                      "2026-08-02T09:00:00Z", "PASS"),
            TECH)
        validate_error(resp, ApiErrorId.ERR_ROUTE_SEQUENCE_VIOLATION)

        done1 = perform_operation(op1["id"], "STN-CRANK-11",
                                  "2026-08-02T08:00:00Z",
                                  "2026-08-02T09:00:00Z", "PASS")
        assert done1["status"] == "COMPLETED"

        done2 = perform_operation(op2["id"], "STN-BORE-1",
                                  "2026-08-02T09:00:00Z",
                                  "2026-08-02T10:00:00Z", "PASS")
        assert done2["status"] == "COMPLETED", (
            "sequence 2 performs normally once sequence 1 is complete")


class TestWindowShapeValidation:
    def test_window_end_not_after_start_rejected(self, api):
        """PRD §3.6: "The performer supplies the `station_code`, the
        occupation window as `scheduled_start` and `scheduled_end` (the end
        strictly after the start, on pain of `ERR_VALIDATION`), and the
        `result` — `PASS` or `FAIL`."
        PRD §3.8: "A `ShopTechnician` records a dyno test against the engine,
        supplying the `dyno_cell_code`, the test window `started_at` and
        `ended_at` (the end strictly after the start), and the three
        measurements: `horsepower`, `oil_pressure_psi`, and `coolant_temp_f`."

        Design: Corner/validations/window_end_not_after_start_rejected
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-WIN",
                                         name="Window Cores")
        spec = create_active_spec(application_code="S10-1995")
        wo_id, op1 = _wo_in_machining_with_pending_op(distributor, spec)

        resp = api.perform_operation(
            op1["id"],
            perform_operation_payload("STN-WIN", "2026-08-02T09:00:00Z",
                                      "2026-08-02T08:00:00Z", "PASS"),
            TECH)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

        done = perform_operation(op1["id"], "STN-WIN", "2026-08-02T08:00:00Z",
                                 "2026-08-02T09:00:00Z", "PASS")
        assert done["status"] == "COMPLETED", (
            "clean perform after the rejection proves no state damage")

        # Drive on to DYNO_TEST and exercise the dyno window rule.
        wo = advance_work_order(wo_id, "ASSEMBLY")
        engine_id = wo["reman_engine_id"]
        advance_work_order(wo_id, "DYNO_TEST")
        resp2 = api.record_dyno_test(
            engine_id,
            record_dyno_test_payload("CELL-WIN", "2026-08-03T08:00:00Z",
                                     "2026-08-03T08:00:00Z"),
            TECH)
        validate_error(resp2, ApiErrorId.ERR_VALIDATION)


class TestStationScheduling:
    def test_station_overlapping_window_rejected(self, api):
        """PRD §3.6: "First, station occupancy: no other operation — of any
        status, excluding the one being performed — may hold a stored window
        on the same `station_code` that overlaps the requested half-open
        interval from `scheduled_start` up to but not including
        `scheduled_end`."
        PRD §3.6: "An actual overlap is rejected with
        `ERR_STATION_SCHEDULE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/station_window_half_open_overlap
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-STN",
                                         name="Station Cores")
        spec = create_active_spec(application_code="S10-1999")
        wa_id, op_a = _wo_in_machining_with_pending_op(distributor, spec)
        wb_id, op_b = _wo_in_machining_with_pending_op(distributor, spec)
        perform_operation(op_a["id"], "STN-SHARED", "2026-08-02T10:00:00Z",
                          "2026-08-02T11:00:00Z", "PASS")

        resp = api.perform_operation(
            op_b["id"],
            perform_operation_payload("STN-SHARED", "2026-08-02T10:30:00Z",
                                      "2026-08-02T11:30:00Z", "PASS"),
            TECH)
        validate_error(resp, ApiErrorId.ERR_STATION_SCHEDULE_OVERLAP)

        op_b_after = list_operations(wb_id)[0]
        assert op_b_after["status"] == "PENDING"
        assert op_b_after["attempt_count"] == 0, "rejection leaves no trace"
        assert op_b_after["station_code"] is None

    def test_station_exact_adjacency_allowed(self, api):
        """PRD §3.6: "Adjacency is explicitly allowed: an existing window
        ending exactly at the new window's start, or a new window ending
        exactly at an existing window's start, does not conflict."

        Design: Difficulty/resource_temporal_overlap/station_window_half_open_overlap
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-STN",
                                         name="Station Cores")
        spec = create_active_spec(application_code="S10-1999")
        wa_id, op_a = _wo_in_machining_with_pending_op(distributor, spec)
        wb_id, op_b = _wo_in_machining_with_pending_op(distributor, spec)
        perform_operation(op_a["id"], "STN-SHARED", "2026-08-02T10:00:00Z",
                          "2026-08-02T11:00:00Z", "PASS")

        done = perform_operation(op_b["id"], "STN-SHARED",
                                 "2026-08-02T11:00:00Z",
                                 "2026-08-02T12:00:00Z", "PASS")
        assert done["status"] == "COMPLETED", (
            "a window starting exactly at the prior window's end is adjacent, "
            "not overlapping")
        assert done["attempt_count"] == 1


class TestOperationDeclarationOcc:
    def test_occ_operation_create_stale_work_order_version(self, api):
        """PRD §2.9: "A route-plan extension — declaring a machining operation
        on a work order — must carry `expected_work_order_version`, set to the
        work order's `version` as last observed by the client. A mismatch with
        the work order's current `version` is likewise rejected with
        `ERR_STALE_VERSION` (HTTP 412)".
        PRD §2.9: "Every successful operation declaration itself increments
        the work order's `version` by 1, so two sequential declarations must
        each re-read the work order."

        Design: Corner/cross_cutting_layers/occ_operation_create_stale_work_order_version
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-OCW",
                                         name="OCC Cores")
        spec = create_active_spec(application_code="CAPRICE-1993",
                                  required_op_sequence=["CRANK_GRIND", "BORE"])
        ret = create_graded_return(distributor, spec)
        wo = open_work_order(ret)
        wo = advance_work_order(wo["id"], "TEARDOWN")
        stale_version = wo["version"]

        first = validate_success(api.declare_operation(
            wo["id"],
            declare_operation_payload("CRANK_GRIND", 1, stale_version),
            TECH), 201)
        assert first["status"] == "PENDING"

        resp = api.declare_operation(
            wo["id"],
            declare_operation_payload("BORE", 2, stale_version),
            TECH)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh = get_work_order(wo["id"])
        assert fresh["version"] == stale_version + 1, (
            "the first declaration incremented the work order version")

        second = validate_success(api.declare_operation(
            wo["id"],
            declare_operation_payload("BORE", 2, fresh["version"]),
            TECH), 201)
        assert second["status"] == "PENDING"

        ops, meta = validate_paginated(api.list_operations(wo["id"], ADMIN))
        assert len(ops) == 2, "both declarations are on the route now"
