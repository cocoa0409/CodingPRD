"""Non-linear state-machine depth tests: the custom-order revision cycle and the
repair-ticket fork-join + QC rework loop.

Translates queue-A difficulty instances under rule_id non_linear_state_machine.
"""
import pytest
from test_helpers import (
    validate_success,
    create_design_review_custom_order,
    create_assessed_repair_ticket,
    create_in_repair_ticket_via_parts,
    TEST_USERS,
)

SA = TEST_USERS["sales_associate_headers"]
GS = TEST_USERS["goldsmith_headers"]
SM = TEST_USERS["store_manager_headers"]


class TestCustomOrderRevisionCycle:
    def test_revision_loop_returns_to_design_review_with_count_one(self, api):
        """PRD §3.3: "Requesting a revision transitions `DESIGN_REVIEW → IN_DESIGN` and
        increments `revision_count` by 1, reopening the design phase; this is the cyclic
        loop `DESIGN_REVIEW → IN_DESIGN → DESIGN_REVIEW`."

        Design: Difficulty/non_linear_state_machine/custom_order_cyclic_revision_loop
        """
        order, _ = create_design_review_custom_order(
            deposit_cents=90000, estimated_materials_cents=200000, design_fee_cents=50000
        )
        # Request a revision, then re-submit for review -> back in DESIGN_REVIEW.
        order = validate_success(
            api.request_revision_custom_order(order["id"], {"expected_version": order["version"]}, SA),
            200,
        )
        assert order["status"] == "IN_DESIGN"
        order = validate_success(
            api.submit_review_custom_order(order["id"], {"expected_version": order["version"]}, GS),
            200,
        )
        assert order["status"] == "DESIGN_REVIEW"
        assert order["revision_count"] == 1

    def test_request_revision_moves_review_back_to_in_design(self, api):
        """PRD §3.3: "Requesting a revision transitions `DESIGN_REVIEW → IN_DESIGN` and
        increments `revision_count` by 1, reopening the design phase; this is the cyclic
        loop `DESIGN_REVIEW → IN_DESIGN → DESIGN_REVIEW`."

        Design: Difficulty/non_linear_state_machine/custom_order_cyclic_revision_loop
        """
        order, _ = create_design_review_custom_order(
            deposit_cents=90000, estimated_materials_cents=200000, design_fee_cents=50000
        )
        assert order["revision_count"] == 0
        order = validate_success(
            api.request_revision_custom_order(order["id"], {"expected_version": order["version"]}, SA),
            200,
        )
        assert order["status"] == "IN_DESIGN"
        assert order["revision_count"] == 1


class TestRepairForkJoinAndQcLoop:
    def test_parts_branch_join_then_qc_failure_returns_to_repair(self, api):
        """PRD §3.4: "If the job needs parts, the goldsmith routes it
        `ASSESSED → AWAITING_PARTS`."
        PRD §3.4: "while failing QC moves `QC → IN_REPAIR`, sending the piece back for
        rework (the rework loop)."

        Design: Difficulty/non_linear_state_machine/repair_ticket_forkjoin_and_qc_loop
        """
        ticket, _ = create_in_repair_ticket_via_parts(8000, 15000, repair_kind="RESIZE")
        ticket = validate_success(
            api.submit_qc_repair_ticket(ticket["id"], {"expected_version": ticket["version"]}, GS), 200
        )
        assert ticket["status"] == "QC"
        ticket = validate_success(
            api.fail_qc_repair_ticket(ticket["id"], {"expected_version": ticket["version"]}, SM), 200
        )
        assert ticket["status"] == "IN_REPAIR"
        assert ticket["total_cents"] == 23000

    def test_no_parts_branch_reaches_in_repair_directly(self, api):
        """PRD §3.4: "Alternatively, if no parts are needed, the goldsmith starts work
        directly, moving `ASSESSED → IN_REPAIR` and skipping the parts branch. Both branches
        join at `IN_REPAIR`."

        Design: Difficulty/non_linear_state_machine/repair_ticket_forkjoin_and_qc_loop
        """
        ticket, _ = create_assessed_repair_ticket(0, 15000, repair_kind="POLISH")
        assert ticket["status"] == "ASSESSED"
        ticket = validate_success(
            api.start_repair_repair_ticket(ticket["id"], {"expected_version": ticket["version"]}, GS),
            200,
        )
        assert ticket["status"] == "IN_REPAIR"
