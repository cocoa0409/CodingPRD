"""Validation-precedence pairs, cross-entity state dependencies, temporal-overlap
conflicts, and compensating-action invariants.

Difficulty queue (depth): priority-pair conflicts (state vs safety, constraint vs
fiscal), WorkOrder->Routing and WorkOrderOperation->Machine dependencies,
half-open run-log overlap vs closed-interval setup-buffer, and the lot/WIP
conservation invariants under reversal.
"""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error,
    TEST_USERS,
    setup_started_single_op_wo,
    setup_released_work_order,
    setup_planned_work_order_released_routing,
    setup_machine_with_run_logs,
    setup_released_wo_with_demand_and_lot,
    setup_pending_scrap_on_started_op,
    create_product, create_machine, create_draft_routing_with_ops,
    create_planned_work_order,
    assert_lot_conservation, assert_wip_conservation,
)
from test_helpers import api_client as _ac

ENG = TEST_USERS["manufacturing_engineer_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
OPERATOR = TEST_USERS["machine_operator_headers"]
INSPECTOR = TEST_USERS["quality_inspector_headers"]


class TestValidationPrecedencePairs:
    def test_machine_down_on_valid_state_start_returns_machine_down(self, api):
        """PRD §3.5: "The referenced machine must not be DOWN, or the start is
        rejected with ERR_MACHINE_DOWN."
        PRD §2.9: "State — the target resource is in a state from which the requested
        transition is defined; otherwise ERR_INVALID_STATE (409)."

        Design: Difficulty/priority_pair_validation_conflict/machine_down_beats_traveler_not_signed_on_start_vs_complete
        """
        ctx = setup_released_work_order(order_qty=1)
        woop_id = ctx["woops"][0]["id"]
        machine_id = ctx["machine"]["id"]
        # op is in a valid 'from' state (QUEUED) so the state check passes; the DOWN
        # machine business-safety check fires.
        get_success_data(api.set_machine_status(machine_id, {"status": "DOWN"}, OPERATOR))
        resp = api.start_operation(woop_id, {"units_in": 1}, OPERATOR)
        validate_error(resp, "ERR_MACHINE_DOWN", 409)

    def test_machine_down_not_reported_as_invalid_state(self, api):
        """PRD §3.5: "The referenced machine must not be DOWN, or the start is
        rejected with ERR_MACHINE_DOWN."
        PRD §2.9: "the system evaluates them in a fixed order and returns the error
        for the first rule that fails, so that the same request always fails for the
        same, most-significant reason."

        Design: Difficulty/priority_pair_validation_conflict/machine_down_beats_traveler_not_signed_on_start_vs_complete
        """
        ctx = setup_released_work_order(order_qty=1)
        woop_id = ctx["woops"][0]["id"]
        get_success_data(api.set_machine_status(ctx["machine"]["id"], {"status": "DOWN"}, OPERATOR))
        resp = api.start_operation(woop_id, {"units_in": 1}, OPERATOR)
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_MACHINE_DOWN"

    def test_scrap_qty_exceeds_available_units_rejected(self, api):
        """PRD §3.7: "At creation the requested quantity must not exceed the
        operation's still-available units — that is, the node's units_in minus the
        units already recorded in its scrap_qty — or the request is rejected with
        ERR_SCRAP_QTY_EXCEEDS."

        Design: Difficulty/priority_pair_validation_conflict/scrap_qty_exceeds_beats_lot_fiscal_when_both_violable
        """
        ctx = setup_started_single_op_wo(order_qty=2, units_in=2, unit_cost_cents=300)
        resp = api.create_scrap_disposition(
            ctx["woop"]["id"], {"quantity": 5, "defect_code": "OVER"}, OPERATOR)
        validate_error(resp, "ERR_SCRAP_QTY_EXCEEDS", 422)

    def test_scrap_qty_exceeds_returns_422(self, api):
        """PRD §3.7: "At creation the requested quantity must not exceed the
        operation's still-available units — that is, the node's units_in minus the
        units already recorded in its scrap_qty — or the request is rejected with
        ERR_SCRAP_QTY_EXCEEDS."

        Design: Difficulty/priority_pair_validation_conflict/scrap_qty_exceeds_beats_lot_fiscal_when_both_violable
        """
        ctx = setup_started_single_op_wo(order_qty=2, units_in=2, unit_cost_cents=300)
        resp = api.create_scrap_disposition(
            ctx["woop"]["id"], {"quantity": 5, "defect_code": "OVER"}, OPERATOR)
        assert resp.status_code == 422
        assert resp.json()["data"]["error_id"] == "ERR_SCRAP_QTY_EXCEEDS"


class TestCrossEntityStateDependencies:
    def test_release_work_order_requires_routing_released(self, api):
        """PRD §3.4: "Release is permitted only when the referenced routing is in
        RELEASED status — otherwise the release is rejected with
        ERR_ROUTING_NOT_RELEASED".

        Design: Difficulty/cross_entity_state_dependency/workorder_release_requires_routing_released
        """
        # DRAFT routing (not released), WO PLANNED.
        fg = create_product(product_type="FINISHED_GOOD")
        machine = create_machine()
        routing, _ = create_draft_routing_with_ops(
            fg["id"], machine["id"], ops=[{"sequence_no": 10, "ideal_cycle_time_secs": 100}])
        wo = create_planned_work_order(fg["id"], routing["id"], order_qty=1)
        resp = api.release_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, PLANNER)
        validate_error(resp, "ERR_ROUTING_NOT_RELEASED", 409)
        # work order remains PLANNED
        wo_now = validate_success(api.get_work_order(wo["id"], PLANNER))
        assert wo_now["status"] == "PLANNED"

    def test_release_against_draft_routing_leaves_order_planned(self, api):
        """PRD §3.4: "Release is permitted only when the referenced routing is in
        RELEASED status — otherwise the release is rejected with
        ERR_ROUTING_NOT_RELEASED".

        Design: Difficulty/cross_entity_state_dependency/workorder_release_requires_routing_released
        """
        fg = create_product(product_type="FINISHED_GOOD")
        machine = create_machine()
        routing, _ = create_draft_routing_with_ops(
            fg["id"], machine["id"], ops=[{"sequence_no": 10, "ideal_cycle_time_secs": 100}])
        wo = create_planned_work_order(fg["id"], routing["id"], order_qty=1)
        resp = api.release_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, PLANNER)
        assert resp.json()["data"]["error_id"] == "ERR_ROUTING_NOT_RELEASED"

    def test_start_op_on_down_machine_rejected(self, api):
        """PRD §3.5: "The referenced machine must not be DOWN, or the start is
        rejected with ERR_MACHINE_DOWN."

        Design: Difficulty/cross_entity_state_dependency/workorderoperation_start_requires_machine_not_down
        """
        ctx = setup_released_work_order(order_qty=1)
        woop_id = ctx["woops"][0]["id"]
        get_success_data(api.set_machine_status(ctx["machine"]["id"], {"status": "DOWN"}, OPERATOR))
        resp = api.start_operation(woop_id, {"units_in": 1}, OPERATOR)
        validate_error(resp, "ERR_MACHINE_DOWN", 409)

    def test_start_op_down_machine_returns_409(self, api):
        """PRD §3.5: "The referenced machine must not be DOWN, or the start is
        rejected with ERR_MACHINE_DOWN."

        Design: Difficulty/cross_entity_state_dependency/workorderoperation_start_requires_machine_not_down
        """
        ctx = setup_released_work_order(order_qty=1)
        get_success_data(api.set_machine_status(ctx["machine"]["id"], {"status": "DOWN"}, OPERATOR))
        resp = api.start_operation(ctx["woops"][0]["id"], {"units_in": 1}, OPERATOR)
        assert resp.status_code == 409
        assert resp.json()["data"]["error_id"] == "ERR_MACHINE_DOWN"


class TestTemporalOverlaps:
    def test_runlog_halfopen_overlap_rejected(self, api):
        """PRD §3.3: "A new run-log window may not overlap any existing window
        already recorded for the same machine; because the interval is half-open, a
        window that starts exactly when another ends does not overlap, but any
        genuine overlap is rejected with ERR_RUNLOG_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/machine_runlog_halfopen_overlap_rejected_adjacency_ok
        """
        ctx = setup_machine_with_run_logs(
            planned_production_secs=28800,
            run_logs=[{"window_start": "2026-06-01T00:00:00.000Z",
                       "window_end": "2026-06-01T04:00:00.000Z",
                       "run_time_secs": 10000, "total_units": 100, "good_units": 100}])
        resp = api.create_run_log(ctx["machine"]["id"], {
            "window_start": "2026-06-01T03:00:00.000Z",
            "window_end": "2026-06-01T05:00:00.000Z",
            "run_time_secs": 5000, "total_units": 50, "good_units": 50}, OPERATOR)
        validate_error(resp, "ERR_RUNLOG_OVERLAP", 409)

    def test_runlog_adjacent_window_accepted(self, api):
        """PRD §3.3: "because the interval is half-open, a window that starts exactly
        when another ends does not overlap, but any genuine overlap is rejected with
        ERR_RUNLOG_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/machine_runlog_halfopen_overlap_rejected_adjacency_ok
        """
        ctx = setup_machine_with_run_logs(
            planned_production_secs=28800,
            run_logs=[{"window_start": "2026-06-01T00:00:00.000Z",
                       "window_end": "2026-06-01T04:00:00.000Z",
                       "run_time_secs": 10000, "total_units": 100, "good_units": 100}])
        # exactly adjacent [04:00,06:00) — end of prior is exclusive, so accepted.
        resp = api.create_run_log(ctx["machine"]["id"], {
            "window_start": "2026-06-01T04:00:00.000Z",
            "window_end": "2026-06-01T06:00:00.000Z",
            "run_time_secs": 5000, "total_units": 50, "good_units": 50}, OPERATOR)
        validate_success(api.get_machine(ctx["machine"]["id"], OPERATOR))  # sanity
        assert resp.status_code == 201, resp.text

    def test_setup_buffer_conflict_on_same_work_center(self, api):
        """PRD §3.5: "a start is rejected with ERR_SETUP_BUFFER_CONFLICT when its
        window would begin at or before the prior operation's scheduled_end extended
        by that operation's setup_buffer_secs — the buffered interval is treated as
        closed, so a window that begins exactly at the buffered end-instant still
        conflicts."

        Design: Difficulty/resource_temporal_overlap/workcenter_setup_buffer_conflict_closed_interval_plus_buffer
        """
        ctx = setup_released_work_order(order_qty=1, ops=[
            {"sequence_no": 10, "ideal_cycle_time_secs": 100, "setup_buffer_secs": 600},
            {"sequence_no": 20, "ideal_cycle_time_secs": 100, "setup_buffer_secs": 0}])
        woop1_id = ctx["woops"][0]["id"]
        woop2_id = ctx["woops"][1]["id"]
        # op1 scheduled [10:00,10:30] PASS-signed, started, completed.
        get_success_data(api.create_signoff(woop1_id, {"result": "PASS"}, INSPECTOR))
        get_success_data(api.start_operation(woop1_id, {
            "scheduled_start": "2026-06-01T10:00:00.000Z",
            "scheduled_end": "2026-06-01T10:30:00.000Z", "units_in": 1}, OPERATOR))
        get_success_data(api.complete_operation(woop1_id, {"good_qty": 1}, OPERATOR))
        # op2 start at 10:35 — only 300s after prior end, buffer is 600s -> conflict.
        resp = api.start_operation(woop2_id, {
            "scheduled_start": "2026-06-01T10:35:00.000Z",
            "scheduled_end": "2026-06-01T11:00:00.000Z", "units_in": 1}, OPERATOR)
        validate_error(resp, "ERR_SETUP_BUFFER_CONFLICT", 409)

    def test_setup_buffer_conflict_returns_409(self, api):
        """PRD §3.5: "a start is rejected with ERR_SETUP_BUFFER_CONFLICT when its
        window would begin at or before the prior operation's scheduled_end extended
        by that operation's setup_buffer_secs — the buffered interval is treated as
        closed, so a window that begins exactly at the buffered end-instant still
        conflicts."

        Design: Difficulty/resource_temporal_overlap/workcenter_setup_buffer_conflict_closed_interval_plus_buffer
        """
        ctx = setup_released_work_order(order_qty=1, ops=[
            {"sequence_no": 10, "ideal_cycle_time_secs": 100, "setup_buffer_secs": 600},
            {"sequence_no": 20, "ideal_cycle_time_secs": 100, "setup_buffer_secs": 0}])
        woop1_id = ctx["woops"][0]["id"]
        woop2_id = ctx["woops"][1]["id"]
        get_success_data(api.create_signoff(woop1_id, {"result": "PASS"}, INSPECTOR))
        get_success_data(api.start_operation(woop1_id, {
            "scheduled_start": "2026-06-01T10:00:00.000Z",
            "scheduled_end": "2026-06-01T10:30:00.000Z", "units_in": 1}, OPERATOR))
        get_success_data(api.complete_operation(woop1_id, {"good_qty": 1}, OPERATOR))
        resp = api.start_operation(woop2_id, {
            "scheduled_start": "2026-06-01T10:35:00.000Z",
            "scheduled_end": "2026-06-01T11:00:00.000Z", "units_in": 1}, OPERATOR)
        assert resp.status_code == 409
        assert resp.json()["data"]["error_id"] == "ERR_SETUP_BUFFER_CONFLICT"


class TestCompensatingInvariants:
    def test_cancel_reverses_lot_issue_restoring_on_hand(self, api):
        """PRD §3.9: "this richer cancellation reverses every non-reversed lot issue
        for the order — restoring each source lot's on_hand_qty and marking the issue
        reversed — deletes the order's component demand rows, sets the status to
        CANCELLED, and increments the order's version."

        Design: Difficulty/compensating_invariant/lot_quantity_conserved_under_issue_then_cancel_reversal
        """
        ctx = setup_released_wo_with_demand_and_lot(
            quantity_per=2, scrap_factor_pct=0, raw_unit_cost=100, received_qty=5, order_qty=1)
        # issue 2 from the lot
        get_success_data(api.create_lot_issue({
            "component_demand_id": ctx["demand"]["id"], "lot_id": ctx["lot"]["id"],
            "work_order_operation_id": ctx["woop"]["id"], "issued_qty": 2}, OPERATOR))
        # cancel the RELEASED WO (no op started)
        get_success_data(api.cancel_work_order(ctx["work_order"]["id"], PLANNER))
        lot = validate_success(api.get_lot(ctx["lot"]["id"], OPERATOR))
        assert lot["on_hand_qty"] == 5, lot["on_hand_qty"]
        assert lot["issued_qty"] == 0, lot["issued_qty"]

    def test_cancel_reversal_preserves_lot_conservation(self, api):
        """PRD §3.8: "thereafter the conservation invariant on_hand_qty plus
        issued_qty equals received_qty is held at all times."

        Design: Difficulty/compensating_invariant/lot_quantity_conserved_under_issue_then_cancel_reversal
        """
        ctx = setup_released_wo_with_demand_and_lot(
            quantity_per=2, scrap_factor_pct=0, raw_unit_cost=100, received_qty=5, order_qty=1)
        get_success_data(api.create_lot_issue({
            "component_demand_id": ctx["demand"]["id"], "lot_id": ctx["lot"]["id"],
            "work_order_operation_id": ctx["woop"]["id"], "issued_qty": 2}, OPERATOR))
        get_success_data(api.cancel_work_order(ctx["work_order"]["id"], PLANNER))
        lot = validate_success(api.get_lot(ctx["lot"]["id"], OPERATOR))
        assert_lot_conservation(lot)
        assert lot["on_hand_qty"] + lot["issued_qty"] == lot["received_qty"] == 5

    def test_wip_conserved_under_scrap(self, api):
        """PRD §3.4: "wip_qty (the in-process count, which always equals started_qty
        minus completed_qty minus scrapped_qty)".

        Design: Difficulty/compensating_invariant/wip_quantity_conserved_under_scrap_disposition
        """
        ctx = setup_pending_scrap_on_started_op(order_qty=10, scrap_qty=3, unit_cost_cents=400)
        get_success_data(api.disposition_scrap(
            ctx["disposition"]["id"], {"decision": "SCRAP"}, INSPECTOR))
        wo = validate_success(api.get_work_order(ctx["work_order"]["id"], PLANNER))
        assert wo["started_qty"] == 10
        assert wo["scrapped_qty"] == 3
        assert wo["wip_qty"] == 7, wo["wip_qty"]

    def test_wip_invariant_holds_after_scrap(self, api):
        """PRD §3.7: "And it adds that quantity to the parent work order's
        scrapped_qty and recomputes the order's wip_qty."

        Design: Difficulty/compensating_invariant/wip_quantity_conserved_under_scrap_disposition
        """
        ctx = setup_pending_scrap_on_started_op(order_qty=10, scrap_qty=3, unit_cost_cents=400)
        get_success_data(api.disposition_scrap(
            ctx["disposition"]["id"], {"decision": "SCRAP"}, INSPECTOR))
        wo = validate_success(api.get_work_order(ctx["work_order"]["id"], PLANNER))
        assert_wip_conservation(wo)
        assert wo["started_qty"] == wo["completed_qty"] + wo["scrapped_qty"] + wo["wip_qty"]
