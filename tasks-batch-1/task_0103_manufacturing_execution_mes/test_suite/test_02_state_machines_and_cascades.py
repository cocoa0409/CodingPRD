"""Non-linear state machine shapes and transitive cascade chains.

Difficulty queue (depth): the WorkOrderOperation pause/resume cycle, the
ScrapDisposition scrap-vs-rework fork, the depth-3 release explosion cascade,
the depth-4 rework cascade, and the empty-set completion boundary.
"""
import pytest

from test_helpers import (
    get_success_data, validate_success,
    TEST_USERS,
    setup_started_single_op_wo,
    setup_pending_scrap_on_started_op,
    setup_completed_op_then_pending_scrap,
    setup_completed_single_op_wo,
    create_product, create_machine, create_bom_line, create_released_routing,
    create_planned_work_order,
)
from test_helpers import api_client as _ac

ENG = TEST_USERS["manufacturing_engineer_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
OPERATOR = TEST_USERS["machine_operator_headers"]
INSPECTOR = TEST_USERS["quality_inspector_headers"]


class TestPauseResumeCycle:
    def test_resume_returns_paused_op_to_in_progress(self, api):
        """PRD §3.5: "A running node can be paused, moving from IN_PROGRESS to
        PAUSED and returning its machine to AVAILABLE. A PAUSED node can be resumed
        back to IN_PROGRESS, which also requires that its machine is not DOWN".

        Design: Difficulty/non_linear_state_machine/workorderoperation_pause_resume_cycle
        """
        ctx = setup_started_single_op_wo(order_qty=1, units_in=1)
        woop_id = ctx["woop"]["id"]
        get_success_data(api.pause_operation(woop_id, OPERATOR))
        resumed = validate_success(api.resume_operation(woop_id, OPERATOR))
        assert resumed["status"] == "IN_PROGRESS"

    def test_resume_sets_machine_running(self, api):
        """PRD §3.5: "A PAUSED node can be resumed back to IN_PROGRESS, which also
        requires that its machine is not DOWN (again ERR_MACHINE_DOWN otherwise)
        and sets the machine to RUNNING."

        Design: Difficulty/non_linear_state_machine/workorderoperation_pause_resume_cycle
        """
        ctx = setup_started_single_op_wo(order_qty=1, units_in=1)
        woop_id = ctx["woop"]["id"]
        machine_id = ctx["machine"]["id"]
        get_success_data(api.pause_operation(woop_id, OPERATOR))
        validate_success(api.resume_operation(woop_id, OPERATOR))
        machine = validate_success(api.get_machine(machine_id, OPERATOR))
        assert machine["status"] == "RUNNING"

    def test_pause_returns_machine_to_available(self, api):
        """PRD §3.5: "A running node can be paused, moving from IN_PROGRESS to
        PAUSED and returning its machine to AVAILABLE."

        Design: Difficulty/non_linear_state_machine/workorderoperation_pause_resume_cycle
        """
        ctx = setup_started_single_op_wo(order_qty=1, units_in=1)
        paused = validate_success(api.pause_operation(ctx["woop"]["id"], OPERATOR))
        assert paused["status"] == "PAUSED"
        machine = validate_success(api.get_machine(ctx["machine"]["id"], OPERATOR))
        assert machine["status"] == "AVAILABLE"


class TestScrapForkBranch:
    def test_scrap_branch_marks_scrapped_and_computes_cost(self, api):
        """PRD §3.7: "A decision of SCRAP advances the disposition from PENDING to
        SCRAPPED. It computes scrap_cost_cents as the disposition quantity
        multiplied by the affected product's unit_cost_cents."

        Design: Difficulty/non_linear_state_machine/scrapdisposition_fork_join_scrap_vs_rework
        """
        ctx = setup_pending_scrap_on_started_op(order_qty=10, scrap_qty=3, unit_cost_cents=500)
        disp = validate_success(api.disposition_scrap(
            ctx["disposition"]["id"], {"decision": "SCRAP"}, INSPECTOR))
        assert disp["status"] == "SCRAPPED"
        assert disp["scrap_cost_cents"] == 1500, disp["scrap_cost_cents"]

    def test_scrap_branch_debits_work_order_scrapped_qty(self, api):
        """PRD §3.7: "And it adds that quantity to the parent work order's
        scrapped_qty and recomputes the order's wip_qty. This branch debits cost
        and work-in-process and does not reopen the operation."

        Design: Difficulty/non_linear_state_machine/scrapdisposition_fork_join_scrap_vs_rework
        """
        ctx = setup_pending_scrap_on_started_op(order_qty=10, scrap_qty=3, unit_cost_cents=500)
        get_success_data(api.disposition_scrap(
            ctx["disposition"]["id"], {"decision": "SCRAP"}, INSPECTOR))
        wo = validate_success(api.get_work_order(ctx["work_order"]["id"], PLANNER))
        assert wo["scrapped_qty"] == 3, wo["scrapped_qty"]


class TestReleaseExplosionCascade:
    def test_release_explodes_single_component_demand(self, api):
        """PRD §3.4: "Exactly one component demand row is created per distinct
        component product reached — counting both subassemblies and raw materials
        — and quantities from every path that reaches the same component accumulate
        into that single row."

        Design: Difficulty/transitive_cascade/workorder_release_explode_demand_cost_operations_chain
        """
        fg = create_product(product_type="FINISHED_GOOD")
        r1 = create_product(product_type="RAW_MATERIAL", unit_cost_cents=100, lot_controlled=True)
        create_bom_line(fg["id"], r1["id"], quantity_per=2, scrap_factor_pct=0)
        machine = create_machine()
        routing, _ = create_released_routing(fg["id"], machine["id"], ops=[
            {"sequence_no": 10, "ideal_cycle_time_secs": 50},
            {"sequence_no": 20, "ideal_cycle_time_secs": 30}])
        wo = create_planned_work_order(fg["id"], routing["id"], order_qty=4)
        get_success_data(api.release_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, PLANNER))
        demands = validate_success(api.list_work_order_component_demands(wo["id"], PLANNER))
        assert len(demands) == 1, demands
        # required = order_qty(4) * quantity_per(2) / (1-0) = 8 ; cost 8*100 = 800
        assert demands[0]["required_qty"] == 8, demands[0]["required_qty"]
        assert demands[0]["standard_cost_cents"] == 800, demands[0]["standard_cost_cents"]

    def test_release_mints_operations_in_sequence_order(self, api):
        """PRD §3.4: "and it creates one WorkOrderOperation per operation in the
        routing, in ascending sequence order (hop three)."

        Design: Difficulty/transitive_cascade/workorder_release_explode_demand_cost_operations_chain
        """
        fg = create_product(product_type="FINISHED_GOOD")
        r1 = create_product(product_type="RAW_MATERIAL", unit_cost_cents=100, lot_controlled=True)
        create_bom_line(fg["id"], r1["id"], quantity_per=2, scrap_factor_pct=0)
        machine = create_machine()
        routing, _ = create_released_routing(fg["id"], machine["id"], ops=[
            {"sequence_no": 10, "ideal_cycle_time_secs": 50},
            {"sequence_no": 20, "ideal_cycle_time_secs": 30}])
        wo = create_planned_work_order(fg["id"], routing["id"], order_qty=4)
        get_success_data(api.release_work_order(
            wo["id"], {"expected_work_order_version": wo["version"]}, PLANNER))
        woops = validate_success(api.list_work_order_operations(wo["id"], PLANNER))
        assert len(woops) == 2, woops
        assert [w["sequence_no"] for w in woops] == [10, 20]


class TestReworkCascade:
    def test_rework_reopens_op_and_reverts_completion(self, api):
        """PRD §3.7: "A decision of REWORK advances the disposition from PENDING to
        REWORKED, and computes no scrap cost (its scrap_cost_cents stays 0). It sets
        the referenced work-order operation's status to REWORK, reopening it. If the
        reopened operation was the order's final operation, it decreases the work
        order's completed_qty by the disposition quantity and recomputes the order's
        wip_qty."

        Design: Difficulty/transitive_cascade/rework_disposition_reopen_op_revert_completion_void_signoff_chain
        """
        ctx = setup_completed_op_then_pending_scrap(order_qty=5, scrap_qty=2, unit_cost_cents=700)
        disp = validate_success(api.disposition_scrap(
            ctx["disposition"]["id"], {"decision": "REWORK"}, INSPECTOR))
        assert disp["status"] == "REWORKED"
        woop = validate_success(api.get_work_order_operation(ctx["woop"]["id"], PLANNER))
        assert woop["status"] == "REWORK"
        wo = validate_success(api.get_work_order(ctx["work_order"]["id"], PLANNER))
        assert wo["completed_qty"] == 3, wo["completed_qty"]

    def test_rework_voids_pass_signoff_so_recompletion_blocked(self, api):
        """PRD §3.7: "And it voids the operation's existing PASS traveler sign-off so
        the operation must be signed off again before it can re-complete."
        PRD §3.5: "a TravelerSignoff whose result is PASS must already exist for this
        node, or completion is rejected with ERR_TRAVELER_NOT_SIGNED."

        Design: Difficulty/transitive_cascade/rework_disposition_reopen_op_revert_completion_void_signoff_chain
        """
        ctx = setup_completed_op_then_pending_scrap(order_qty=5, scrap_qty=2, unit_cost_cents=700)
        get_success_data(api.disposition_scrap(
            ctx["disposition"]["id"], {"decision": "REWORK"}, INSPECTOR))
        woop_id = ctx["woop"]["id"]
        # resume the REWORK op back to IN_PROGRESS, then attempt complete: the
        # voided PASS sign-off means completion is rejected.
        get_success_data(api.resume_operation(woop_id, OPERATOR))
        from test_helpers import validate_error
        resp = api.complete_operation(woop_id, {"good_qty": 3}, OPERATOR)
        validate_error(resp, "ERR_TRAVELER_NOT_SIGNED")


class TestEmptySetCompletionBoundary:
    def test_complete_workorder_with_no_bom_zero_variance(self, api):
        """PRD §3.4: "A demand's standard_cost_cents is its required_qty multiplied
        by that component's own unit_cost_cents, rounded to whole cents — and because
        a subassembly with no unit cost contributes 0, only priced components add to
        the standard total."
        PRD §3.9: "the standard cost is the sum of standard_cost_cents across the
        order's component demands."

        Design: Difficulty/boundary_precision_check/complete_workorder_with_zero_component_demands_empty_set
        """
        ctx = setup_completed_single_op_wo(order_qty=1)
        wo = validate_success(api.get_work_order(ctx["work_order"]["id"], PLANNER))
        assert wo["material_variance_cents"] == 0, wo["material_variance_cents"]
        assert wo["status"] == "COMPLETED"

    def test_complete_workorder_empty_demands_reaches_completed(self, api):
        """PRD §3.9: "Material variance is the actual material cost minus the standard
        material cost".
        PRD §3.9: "computes the work order's material_variance_cents, sets the status
        to COMPLETED, and increments the order's version."

        Design: Difficulty/boundary_precision_check/complete_workorder_with_zero_component_demands_empty_set
        """
        ctx = setup_completed_single_op_wo(order_qty=1)
        # No BOM -> no demands -> actual 0, standard 0 -> variance 0.
        assert ctx["work_order"]["status"] == "COMPLETED"
        assert ctx["work_order"]["material_variance_cents"] == 0
