"""Corner queue (breadth): OEE non-flag/zero-total cases, labor cost rounding,
business validations, run-log field constraints, and the work-order listing
envelope.
"""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    TEST_USERS,
    setup_machine_with_run_logs, setup_completed_single_op_wo,
    setup_released_routing_for_fg, setup_released_work_order,
    setup_released_wo_with_demand_and_lot,
    create_product, create_machine, create_bom_line, create_draft_routing_with_ops,
    create_planned_work_order,
    signoff_start_complete_op,
)
from test_helpers import api_client as _ac

ENG = TEST_USERS["manufacturing_engineer_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
OPERATOR = TEST_USERS["machine_operator_headers"]
INSPECTOR = TEST_USERS["quality_inspector_headers"]


class TestOeeCornerCases:
    def test_quality_above_floor_not_flagged(self, api):
        """PRD §3.3: "the machine's quality_flagged is set to true when the
        just-computed oee_quality is at or below the quality floor of 0.95, and false
        otherwise; the boundary value of exactly 0.95 does flag."

        Design: Corner/calculations/oee_quality_above_floor_not_flagged
        """
        ctx = setup_machine_with_run_logs(
            planned_production_secs=28800,
            run_logs=[{"window_start": "2026-06-01T00:00:00.000Z",
                       "window_end": "2026-06-01T04:00:00.000Z",
                       "run_time_secs": 10000, "total_units": 200, "good_units": 191}])
        m = validate_success(api.recompute_oee(ctx["machine"]["id"], INSPECTOR))
        # Q = 191/200 = 0.9550 > 0.95 -> not flagged
        assert m["oee_quality"] == 0.9550, m["oee_quality"]
        assert m["quality_flagged"] is False

    def test_zero_total_units_quality_zero(self, api):
        """PRD §3.3: "Quality is the summed good units divided by the summed total
        units, clamped to 0 through 1; if the summed total units is zero, quality is
        taken to be 0."

        Design: Corner/calculations/oee_zero_total_units_quality_zero
        """
        ctx = setup_machine_with_run_logs(
            planned_production_secs=28800,
            run_logs=[{"window_start": "2026-06-01T00:00:00.000Z",
                       "window_end": "2026-06-01T04:00:00.000Z",
                       "run_time_secs": 5000, "total_units": 0, "good_units": 0}])
        m = validate_success(api.recompute_oee(ctx["machine"]["id"], ENG))
        assert m["oee_quality"] == 0.0, m["oee_quality"]
        assert m["oee_overall"] == 0.0, m["oee_overall"]


class TestLaborCost:
    def test_labor_total_round_per_operation_then_sum(self, api):
        """PRD §3.10: "the operation's labor cost is those seconds multiplied by the
        labor rate of 2 cents per second, rounded to whole cents. The reported
        labor_total_cents is the sum of those per-operation labor costs, with each
        operation's labor rounded before summing — summing exact seconds-cost and
        rounding once is the documented naive alternative and is not used."

        Design: Corner/calculations/labor_completion_cost_round_per_op_then_sum
        """
        fg = create_product(product_type="FINISHED_GOOD")
        machine = create_machine()
        routing, _ = create_draft_routing_with_ops(fg["id"], machine["id"], ops=[
            {"sequence_no": 10, "ideal_cycle_time_secs": 12.25},
            {"sequence_no": 20, "ideal_cycle_time_secs": 18.75}])
        get_success_data(api.release_routing(routing["id"], ENG))
        wo = create_planned_work_order(fg["id"], routing["id"], order_qty=1)
        wo = get_success_data(api.release_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, PLANNER))
        woops = get_success_data(api.list_work_order_operations(wo["id"], PLANNER))
        for woop in woops:
            signoff_start_complete_op(woop["id"], units_in=1, good_qty=1)
        get_success_data(api.complete_work_order(wo["id"], PLANNER))
        cost = validate_success(api.get_cost_summary(wo["id"], PLANNER))
        # op1: 12.25*1*2 = 24.5 -> 25 ; op2: 18.75*1*2 = 37.5 -> 38 ; total 63 (not 62)
        assert cost["labor_total_cents"] == 63, cost["labor_total_cents"]


class TestBusinessValidations:
    def test_duplicate_operation_sequence_rejected(self, api):
        """PRD §3.2: "a sequence_no that orders it within the routing (strictly
        greater than 0 and unique within that routing — a duplicate is rejected with
        ERR_DUPLICATE_SEQUENCE, with lower numbers running first)".

        Design: Corner/validations/duplicate_operation_sequence_rejected
        """
        fg = create_product(product_type="FINISHED_GOOD")
        machine = create_machine()
        routing, _ = create_draft_routing_with_ops(
            fg["id"], machine["id"], ops=[{"sequence_no": 10, "ideal_cycle_time_secs": 100}])
        resp = api.create_operation(
            routing["id"], {"machine_id": machine["id"], "sequence_no": 10,
                            "ideal_cycle_time_secs": 60}, ENG)
        validate_error(resp, "ERR_DUPLICATE_SEQUENCE", 409)

    def test_lot_issue_over_on_hand_rejected(self, api):
        """PRD §3.8: "the requested issued_qty must not exceed the source lot's
        on_hand_qty, or the issue is rejected with ERR_INSUFFICIENT_LOT_QTY."

        Design: Corner/validations/lot_issue_over_on_hand_rejected
        """
        ctx = setup_released_wo_with_demand_and_lot(
            quantity_per=2, scrap_factor_pct=0, raw_unit_cost=100, received_qty=5, order_qty=1)
        resp = api.create_lot_issue({
            "component_demand_id": ctx["demand"]["id"], "lot_id": ctx["lot"]["id"],
            "work_order_operation_id": ctx["woop"]["id"], "issued_qty": 6}, OPERATOR)
        validate_error(resp, "ERR_INSUFFICIENT_LOT_QTY", 422)

    def test_lot_issue_product_mismatch_rejected(self, api):
        """PRD §3.8: "the source lot's product must match the demand's component — the
        lot's product_id must equal the demand's component_product_id, or the issue is
        rejected with ERR_LOT_PRODUCT_MISMATCH".

        Design: Corner/validations/lot_issue_product_mismatch_rejected
        """
        # WO with demand for R1; issue a lot of a DIFFERENT raw R9.
        ctx = setup_released_wo_with_demand_and_lot(
            quantity_per=1, scrap_factor_pct=0, raw_unit_cost=100, received_qty=5, order_qty=1)
        r9 = create_product(product_type="RAW_MATERIAL", unit_cost_cents=100, lot_controlled=True)
        l9 = get_success_data(api.create_lot(
            {"product_id": r9["id"], "lot_code": "L-R9", "received_qty": 5}, OPERATOR))
        resp = api.create_lot_issue({
            "component_demand_id": ctx["demand"]["id"], "lot_id": l9["id"],
            "work_order_operation_id": ctx["woop"]["id"], "issued_qty": 1}, OPERATOR)
        validate_error(resp, "ERR_LOT_PRODUCT_MISMATCH", 422)

    def test_bom_cycle_multilevel_rejected(self, api):
        """PRD §3.1: "if the new edge would introduce a cycle anywhere in the
        bill-of-material graph, the line is rejected with ERR_BOM_CYCLE."

        Design: Corner/validations/bom_cycle_multilevel_rejected
        """
        a = create_product(product_type="SUBASSEMBLY", unit_cost_cents=10)
        b = create_product(product_type="SUBASSEMBLY", unit_cost_cents=10)
        c = create_product(product_type="SUBASSEMBLY", unit_cost_cents=10)
        create_bom_line(a["id"], b["id"], quantity_per=1)
        create_bom_line(b["id"], c["id"], quantity_per=1)
        # C -> A would close the cycle A->B->C->A.
        resp = api.create_bom_line(
            {"parent_product_id": c["id"], "component_product_id": a["id"],
             "quantity_per": 1}, ENG)
        validate_error(resp, "ERR_BOM_CYCLE", 409)


class TestRunLogFieldConstraints:
    def test_run_time_exceeds_window_rejected(self, api):
        """PRD §3.3: "The log records the run_time_secs the machine was actually
        running within the window (at least 0 and no greater than the window's own
        duration in seconds)".
        PRD §2.9: "The lowest-precedence check is the generic well-formedness gate:
        required fields present and well-typed and enum members valid, failing which
        the request is rejected with ERR_INVALID_REQUEST (400)."

        Design: Corner/errors/run_log_run_time_exceeds_window_rejected
        """
        machine = create_machine()
        # window span = 3600s; run_time 5000 > 3600 -> invalid
        resp = api.create_run_log(machine["id"], {
            "window_start": "2026-06-01T00:00:00.000Z",
            "window_end": "2026-06-01T01:00:00.000Z",
            "run_time_secs": 5000, "total_units": 10, "good_units": 10}, OPERATOR)
        validate_error(resp, "ERR_INVALID_REQUEST", 400)

    def test_good_units_exceeds_total_rejected(self, api):
        """PRD §3.3: "the good_units that were defect-free (at least 0 and no greater
        than total_units)".

        Design: Corner/errors/run_log_good_exceeds_total_rejected
        """
        machine = create_machine()
        resp = api.create_run_log(machine["id"], {
            "window_start": "2026-06-01T00:00:00.000Z",
            "window_end": "2026-06-01T04:00:00.000Z",
            "run_time_secs": 1000, "total_units": 10, "good_units": 12}, OPERATOR)
        validate_error(resp, "ERR_INVALID_REQUEST", 400)


class TestListing:
    def test_list_work_orders_pagination_envelope(self, api):
        """PRD §2.3: "Every list response includes limit, offset, total_count, and
        has_more in the meta object of the envelope."
        PRD §2.3: "The limit parameter caps the number of items returned; it defaults
        to 10, with a minimum of 1 and a maximum of 100. The offset parameter is the
        number of items to skip and defaults to 0."

        Design: Corner/endpoints/list_workorders_pagination_envelope
        """
        base = setup_released_routing_for_fg()
        create_planned_work_order(base["fg"]["id"], base["routing"]["id"], order_qty=1)
        create_planned_work_order(base["fg"]["id"], base["routing"]["id"], order_qty=2)
        # Both work orders are PLANNED; the paginated envelope must surface them with
        # total_count==2 and has_more==false within the default page of 10.
        resp = api.list_work_orders(PLANNER, params={"limit": 10, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, meta
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
