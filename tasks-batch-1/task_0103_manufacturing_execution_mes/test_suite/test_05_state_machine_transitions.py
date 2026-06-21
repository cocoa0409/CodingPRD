"""Corner queue (breadth): initial states, invalid transitions, terminal-state
lockdown, sequencing/precondition gates, bubble-up, and idempotency.
"""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error,
    TEST_USERS,
    setup_released_routing_for_fg, setup_released_work_order,
    setup_started_single_op_wo, setup_completed_single_op_wo,
    create_planned_work_order,
)
from test_helpers import api_client as _ac

ENG = TEST_USERS["manufacturing_engineer_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
OPERATOR = TEST_USERS["machine_operator_headers"]
INSPECTOR = TEST_USERS["quality_inspector_headers"]


class TestInitialState:
    def test_work_order_initial_state_planned_zero_quantities(self, api):
        """PRD §3.4: "A new work order begins in PLANNED status and carries a family
        of computed quantity fields that all start at 0: started_qty (units that
        entered the first operation), completed_qty (units that passed the final
        operation), scrapped_qty (units scrapped via disposition), wip_qty (the
        in-process count, which always equals started_qty minus completed_qty minus
        scrapped_qty), and material_variance_cents (filled in at completion)."

        Design: Corner/state_machines/workorder_initial_state_planned
        """
        base = setup_released_routing_for_fg()
        wo = validate_success(api.create_work_order(
            {"product_id": base["fg"]["id"], "routing_id": base["routing"]["id"],
             "order_qty": 5}, PLANNER), 201)
        assert wo["status"] == "PLANNED"
        assert wo["started_qty"] == 0
        assert wo["wip_qty"] == 0


class TestInvalidTransitions:
    def test_complete_released_work_order_invalid_state(self, api):
        """PRD §3.9: "a ProductionPlanner completes the work order, advancing it from
        IN_PROCESS to COMPLETED."
        PRD §3.9: "Any cancel, complete, close, or release attempted from a state for
        which the transition is not defined is rejected with ERR_INVALID_STATE."

        Design: Corner/state_machines/complete_workorder_from_released_invalid_state
        """
        ctx = setup_released_work_order(order_qty=1)
        resp = api.complete_work_order(ctx["work_order"]["id"], PLANNER)
        validate_error(resp, "ERR_INVALID_STATE", 409)

    def test_cancel_completed_work_order_invalid_state(self, api):
        """PRD §3.9: "A work order may instead be cancelled by a ProductionPlanner
        from either of two earlier states".
        PRD §3.9: "Any cancel, complete, close, or release attempted from a state for
        which the transition is not defined is rejected with ERR_INVALID_STATE."

        Design: Corner/state_machines/cancel_completed_workorder_invalid_state
        """
        ctx = setup_completed_single_op_wo(order_qty=1)
        resp = api.cancel_work_order(ctx["work_order"]["id"], PLANNER)
        validate_error(resp, "ERR_INVALID_STATE", 409)


class TestSequencingAndPreconditionGates:
    def test_start_operation_out_of_sequence_rejected(self, api):
        """PRD §3.5: "Every work-order operation in the same order with a lower
        sequence_no must already be COMPLETED; starting out of order is rejected with
        ERR_OPERATION_SEQUENCE_VIOLATION."

        Design: Corner/state_machines/start_operation_out_of_sequence_rejected
        """
        ctx = setup_released_work_order(order_qty=1, ops=[
            {"sequence_no": 10, "ideal_cycle_time_secs": 100},
            {"sequence_no": 20, "ideal_cycle_time_secs": 50}])
        woop2_id = ctx["woops"][1]["id"]
        resp = api.start_operation(woop2_id, {"units_in": 1}, OPERATOR)
        validate_error(resp, "ERR_OPERATION_SEQUENCE_VIOLATION", 409)

    def test_complete_operation_without_signoff_rejected(self, api):
        """PRD §3.5: "Completion is gated by the electronic traveler: a
        TravelerSignoff whose result is PASS must already exist for this node, or
        completion is rejected with ERR_TRAVELER_NOT_SIGNED."

        Design: Corner/state_machines/complete_operation_without_signoff_rejected
        """
        ctx = setup_started_single_op_wo(order_qty=1, units_in=1)
        resp = api.complete_operation(ctx["woop"]["id"], {"good_qty": 1}, OPERATOR)
        validate_error(resp, "ERR_TRAVELER_NOT_SIGNED", 409)

    def test_archive_routing_with_active_workorder_rejected(self, api):
        """PRD §3.2: "A RELEASED routing advances from RELEASED to ARCHIVED only when
        no work order in RELEASED or IN_PROCESS status still references that routing".
        PRD §3.2: "Any attempt to release or archive a routing that is not in the
        required starting state is an ERR_INVALID_STATE."

        Design: Corner/state_machines/archive_routing_with_active_workorder_rejected
        """
        ctx = setup_released_work_order(order_qty=1)
        resp = api.archive_routing(ctx["routing"]["id"], ENG)
        validate_error(resp, "ERR_INVALID_STATE", 409)


class TestBubbleUp:
    def test_start_first_op_bubbles_work_order_to_in_process(self, api):
        """PRD §3.5: "if this is the first operation of the order, it bubbles the work
        order forward from PLANNED or RELEASED to IN_PROCESS, sets the order's
        started_qty to its order_qty, and recomputes the order's wip_qty."

        Design: Corner/state_machines/start_first_op_bubbles_workorder_to_in_process
        """
        ctx = setup_released_work_order(order_qty=6)
        woop_id = ctx["woops"][0]["id"]
        get_success_data(api.start_operation(woop_id, {"units_in": 6}, OPERATOR))
        wo = validate_success(api.get_work_order(ctx["work_order"]["id"], PLANNER))
        assert wo["status"] == "IN_PROCESS"
        assert wo["started_qty"] == 6


class TestIdempotency:
    def test_redisposition_scrapped_disposition_invalid_state(self, api):
        """PRD §3.7: "Resolving either way requires the disposition to be PENDING; a
        disposition already SCRAPPED or REWORKED cannot be dispositioned again and
        yields ERR_INVALID_STATE."

        Design: Corner/state_machines/scrap_disposition_already_dispositioned_invalid_state
        """
        ctx = setup_started_single_op_wo(order_qty=10, units_in=10, unit_cost_cents=200)
        disp = get_success_data(api.create_scrap_disposition(
            ctx["woop"]["id"], {"quantity": 2, "defect_code": "X"}, OPERATOR))
        get_success_data(api.disposition_scrap(disp["id"], {"decision": "SCRAP"}, INSPECTOR))
        resp = api.disposition_scrap(disp["id"], {"decision": "REWORK"}, INSPECTOR)
        validate_error(resp, "ERR_INVALID_STATE", 409)
