"""Work order state machine and cross-entity gating (PRD §3.10).

Covers:
- Open → UNDER_REVIEW via /assign
- UNDER_REVIEW → AWAITING_INFO (request-info) → UNDER_REVIEW (submit-info)
- UNDER_REVIEW → RESOLVED (blocked if related_return_id points to non-terminal Return)
- UNDER_REVIEW → ESCALATED → RESOLVED
- RESOLVED → CLOSED
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_active_restaurant,
    create_customer,
    create_work_order_payload,
    get_success_data,
    make_customer_headers,
    open_work_order_for_return,
    resolve_work_order_payload,
    run_to_return_requested,
    validate_error,
    validate_success,
)


class TestWorkOrderClaimFlow:
    def test_assign_opens_under_review(self, api, cs_headers):
        """PRD §3.10: "A CustomerService operator (or PlatformAdmin) claims the ticket,
        recording assigned_cs_user_id as the caller and transitioning the ticket to
        UNDER_REVIEW."

        Claim: /assign on OPEN → status=UNDER_REVIEW and assigned_cs_user_id is set.
        """
        wo = get_success_data(
            api.create_work_order(
                create_work_order_payload(
                    opened_by_role="CUSTOMER_SERVICE",
                    opened_by_id="test-cs-1",
                    category="OTHER",
                ),
                cs_headers,
            )
        )
        assert wo["status"] == "OPEN"
        assert wo["assigned_cs_user_id"] is None

        assigned = validate_success(api.assign_work_order(wo["id"], cs_headers), 200)
        assert assigned["status"] == "UNDER_REVIEW"
        assert assigned["assigned_cs_user_id"] is not None


class TestWorkOrderRequestSubmitCycle:
    def test_request_info_and_submit_info_cycle(self, api, cs_headers):
        """PRD §3.10: "From UNDER_REVIEW, the operator can request additional information
        from the opener — the ticket advances to AWAITING_INFO — and the opener (a
        Customer, Rider, or Restaurant) responds by submitting info, which cycles the
        ticket back to UNDER_REVIEW."

        Claim: request-info → AWAITING_INFO, then submit-info → UNDER_REVIEW.
        """
        customer = create_customer()
        wo = get_success_data(
            api.create_work_order(
                create_work_order_payload(
                    opened_by_role="CUSTOMER",
                    opened_by_id=customer["id"],
                    category="OTHER",
                ),
                make_customer_headers(customer["id"]),
            )
        )
        api.assign_work_order(wo["id"], cs_headers)

        awaiting = validate_success(api.request_info_work_order(wo["id"], cs_headers), 200)
        assert awaiting["status"] == "AWAITING_INFO"

        # Opener responds — PRD §3.10: "When the opener acts, their X-User-ID must match
        # opened_by_id."
        customer_headers = make_customer_headers(customer["id"])
        resumed = validate_success(api.submit_info_work_order(wo["id"], customer_headers), 200)
        assert resumed["status"] == "UNDER_REVIEW"


class TestWorkOrderResolveGating:
    def test_resolve_blocked_while_related_return_non_terminal(self, api, cs_headers):
        """PRD §3.10: "if related_return_id is set, the linked Return's status must be in
        APPROVED or REJECTED before the ticket can move to RESOLVED; attempting to resolve
        while the linked return is still REQUESTED or ESCALATED is rejected with
        ERR_RELATED_RETURN_UNRESOLVED."

        Claim: WorkOrder UNDER_REVIEW + related Return REQUESTED → /resolve returns
        ERR_RELATED_RETURN_UNRESOLVED.

        # difficulty: cross_entity_state_dependency/work_order_resolve_requires_related_return_terminal
        """
        ctx = run_to_return_requested(subtotal_cents=1000, requested_refund_cents=400)
        ret = ctx["return"]
        wo = open_work_order_for_return(ret, actor_headers=cs_headers)
        api.assign_work_order(wo["id"], cs_headers)

        res = api.resolve_work_order(wo["id"], resolve_work_order_payload("x"), cs_headers)
        validate_error(res, "ERR_RELATED_RETURN_UNRESOLVED")

    def test_resolve_succeeds_once_related_return_terminal(self, api, cs_headers):
        """PRD §3.10: "if related_return_id is set, the linked Return's status must be in
        APPROVED or REJECTED before the ticket can move to RESOLVED".

        Claim: after the linked Return is REJECTED (terminal), /resolve succeeds.

        # difficulty: cross_entity_state_dependency/work_order_resolve_requires_related_return_terminal
        """
        ctx = run_to_return_requested(subtotal_cents=1000, requested_refund_cents=400)
        ret = ctx["return"]
        wo = open_work_order_for_return(ret, actor_headers=cs_headers)
        api.assign_work_order(wo["id"], cs_headers)

        # Reject the return — terminal.
        api.reject_return(ret["id"], cs_headers)

        resolved = validate_success(
            api.resolve_work_order(wo["id"], resolve_work_order_payload("done"), cs_headers), 200
        )
        assert resolved["status"] == "RESOLVED"


class TestWorkOrderInvalidState:
    def test_resolve_before_assign_invalid_state(self, api, cs_headers):
        """PRD §2.6 priority 6: "Target resource is in a state from which the requested
        transition is allowed (ERR_INVALID_STATE)."
        PRD §3.10: "From UNDER_REVIEW the operator may either escalate the ticket … or
        resolve it."

        Claim: /resolve on an OPEN (not UNDER_REVIEW/ESCALATED) WorkOrder without any
        related_return linkage → ERR_INVALID_STATE. Serves as the single-failure control
        for the dual-failure priority test below.
        """
        wo = get_success_data(
            api.create_work_order(
                create_work_order_payload(
                    opened_by_role="CUSTOMER_SERVICE",
                    opened_by_id="test-cs-1",
                    category="OTHER",
                ),
                cs_headers,
            )
        )
        res = api.resolve_work_order(wo["id"], resolve_work_order_payload("x"), cs_headers)
        validate_error(res, "ERR_INVALID_STATE")

    def test_resolve_open_with_non_terminal_return_still_invalid_state(self, api, cs_headers):
        """PRD §2.6: validations run in strict priority order — "earlier checks
        short-circuit later ones, which means the error a client sees identifies the first
        failure encountered, not a downstream failure that would have also applied."
        PRD §2.6 priority 6: state (ERR_INVALID_STATE); PRD §2.6 priority 13: cross-entity
        gating (ERR_RELATED_RETURN_UNRESOLVED).

        Claim: OPEN WorkOrder with non-terminal related Return → ERR_INVALID_STATE wins
        (state priority 6 < cross-entity priority 13).

        # difficulty: priority_pair_validation_conflict/state_vs_business_referential_on_return_approve
        """
        ctx = run_to_return_requested(subtotal_cents=1000, requested_refund_cents=400)
        ret = ctx["return"]
        wo = open_work_order_for_return(ret, actor_headers=cs_headers)
        # Do NOT assign — WorkOrder is still OPEN.
        res = api.resolve_work_order(wo["id"], resolve_work_order_payload("x"), cs_headers)
        validate_error(res, "ERR_INVALID_STATE")


class TestWorkOrderClosure:
    def test_close_resolved_goes_closed(self, api, cs_headers):
        """PRD §3.10: "From RESOLVED the ticket is closed (RESOLVED → CLOSED), which is
        terminal."

        Claim: /close on RESOLVED → status=CLOSED.
        """
        wo = get_success_data(
            api.create_work_order(
                create_work_order_payload(
                    opened_by_role="CUSTOMER_SERVICE",
                    opened_by_id="test-cs-1",
                    category="OTHER",
                ),
                cs_headers,
            )
        )
        api.assign_work_order(wo["id"], cs_headers)
        api.resolve_work_order(wo["id"], resolve_work_order_payload("resolved"), cs_headers)
        closed = validate_success(api.close_work_order(wo["id"], cs_headers), 200)
        assert closed["status"] == "CLOSED"
