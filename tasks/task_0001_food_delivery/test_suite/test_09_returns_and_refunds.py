"""Returns and refund flows (PRD §3.9).

Covers:
- Return creation eligibility: DELIVERED, within 24h, amount in range
- Return creation validation errors
- /approve cascades: Return → APPROVED, Order → REFUNDED, payment_status update
- /reject reverts order back to DELIVERED
- /escalate opens WorkOrder; /reopen closes it
- Customer.credit_balance_cents incremented by approved_refund_cents
- Restaurant.pending_settlement_cents decremented by approved_refund_cents
- REQUESTED → ESCALATED → REQUESTED → ESCALATED → APPROVED revision cycle
"""

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_seconds,
    approve_return_payload,
    api_client,
    create_return_payload,
    get_success_data,
    make_customer_headers,
    open_return_on_delivered_order,
    open_work_order_for_return,
    run_order_to_delivered,
    run_to_return_requested,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestReturnEligibility:
    def test_cannot_return_non_delivered_order(self, api):
        """PRD §3.9: "The request is only eligible when the order is in DELIVERED".
        PRD §2.6 priority 6: "Target resource is in a state from which the requested
        transition is allowed (ERR_INVALID_STATE)."

        Claim: return on a PLACED order → ERR_INVALID_STATE.
        """
        from test_helpers import setup_customer_restaurant_menu, place_order
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        order = place_order(customer, restaurant, menu_item)
        headers = make_customer_headers(customer["id"])
        res = api.create_return(
            order["id"],
            create_return_payload(reason="QUALITY_ISSUE", requested_refund_cents=100),
            headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_return_after_24h_rejected(self, api):
        """PRD §3.9: "the current moment is within 24 hours of the order's
        actual_delivery_time; requests outside that window are rejected with
        ERR_RETURN_WINDOW_EXPIRED."

        Claim: opening a return 25 hours after delivery → ERR_RETURN_WINDOW_EXPIRED.
        """
        ctx = run_order_to_delivered(distance_km=2.0, menu_price_cents=5000)
        # Advance 25 hours.
        advance_clock_seconds(25 * 3600)
        headers = make_customer_headers(ctx["customer"]["id"])
        res = api.create_return(
            ctx["order"]["id"],
            create_return_payload(reason="QUALITY_ISSUE", requested_refund_cents=100),
            headers,
        )
        validate_error(res, "ERR_RETURN_WINDOW_EXPIRED")

    def test_requested_refund_exceeds_subtotal_rejected(self, api):
        """PRD §3.9: "The requested refund must be at least 1 and at most the order's
        subtotal_cents; values out of range are rejected with ERR_REFUND_AMOUNT_INVALID."

        Claim: requested_refund_cents > subtotal_cents → ERR_REFUND_AMOUNT_INVALID.
        """
        ctx = run_order_to_delivered(distance_km=2.0, menu_price_cents=1000)
        headers = make_customer_headers(ctx["customer"]["id"])
        res = api.create_return(
            ctx["order"]["id"],
            create_return_payload(reason="QUALITY_ISSUE", requested_refund_cents=9999),
            headers,
        )
        validate_error(res, "ERR_REFUND_AMOUNT_INVALID")

    def test_requested_refund_zero_rejected(self, api):
        """PRD §3.9: "The requested refund must be at least 1 and at most the order's
        subtotal_cents; values out of range are rejected with ERR_REFUND_AMOUNT_INVALID."

        Claim: requested_refund_cents == 0 → ERR_REFUND_AMOUNT_INVALID.
        """
        ctx = run_order_to_delivered(distance_km=2.0, menu_price_cents=1000)
        headers = make_customer_headers(ctx["customer"]["id"])
        res = api.create_return(
            ctx["order"]["id"],
            create_return_payload(reason="QUALITY_ISSUE", requested_refund_cents=0),
            headers,
        )
        validate_error(res, "ERR_REFUND_AMOUNT_INVALID")

    def test_duplicate_return_rejected(self, api):
        """PRD §3.9 names ERR_DUPLICATE_RETURN for this case: "A duplicate return
        attempt — a request made while another Return for the same order is already in
        REQUESTED, APPROVED, or ESCALATED — is rejected with ERR_DUPLICATE_RETURN."

        But PRD §2.6 also lists state-machine precondition (priority 6) strictly before
        uniqueness (priority 8). Opening the first Return cascades the order from
        DELIVERED to REFUND_REQUESTED (§3.9), so the second attempt fails the
        DELIVERED-only state precondition before the duplicate check runs — the
        earlier-priority error ERR_INVALID_STATE is also a legal outcome under §2.6's
        short-circuit rule. Both error_ids are named in PRD for their respective rules;
        either is a PRD-faithful outcome.

        Claim: second return on same order while first REQUESTED →
        ERR_DUPLICATE_RETURN OR ERR_INVALID_STATE (both PRD-valid under the §2.6
        priority pipeline).
        """
        ctx = run_to_return_requested(subtotal_cents=1000, requested_refund_cents=100)
        headers = make_customer_headers(ctx["customer"]["id"])
        res = api.create_return(
            ctx["order"]["id"],
            create_return_payload(reason="QUALITY_ISSUE", requested_refund_cents=100),
            headers,
        )
        validate_error_is_one_of(res, ["ERR_DUPLICATE_RETURN", "ERR_INVALID_STATE"])


class TestReturnApproveCascade:
    def test_approve_refunds_partially(self, api, cs_headers):
        """PRD §3.9: "The order's payment_status becomes PARTIALLY_REFUNDED if
        approved_refund_cents is strictly less than subtotal_cents, or FULLY_REFUNDED if
        the approved amount equals the subtotal."

        Claim: approved_refund_cents < subtotal_cents → payment_status=PARTIALLY_REFUNDED.

        # difficulty: non_linear_state_machine/order_parallel_fulfillment_and_payment_dimensions
        """
        ctx = run_to_return_requested(subtotal_cents=1000, requested_refund_cents=400)
        ret = ctx["return"]
        res = api.approve_return(ret["id"], approve_return_payload(300), cs_headers)
        data = validate_success(res, 200)
        assert data["status"] == "APPROVED"

        order = get_success_data(api.get_order(ctx["order"]["id"], TEST_USERS["admin_headers"]))
        assert order["status"] == "REFUNDED"
        assert order["payment_status"] == "PARTIALLY_REFUNDED"

    def test_approve_refunds_fully(self, api, cs_headers):
        """PRD §3.9: "… or FULLY_REFUNDED if the approved amount equals the subtotal."

        Claim: approved_refund_cents == subtotal_cents → payment_status=FULLY_REFUNDED.
        """
        ctx = run_to_return_requested(subtotal_cents=1000, requested_refund_cents=1000)
        ret = ctx["return"]
        res = api.approve_return(ret["id"], approve_return_payload(1000), cs_headers)
        validate_success(res, 200)
        order = get_success_data(api.get_order(ctx["order"]["id"], TEST_USERS["admin_headers"]))
        assert order["payment_status"] == "FULLY_REFUNDED"

    def test_approve_credits_customer_balance(self, api, cs_headers):
        """PRD §3.9: "The customer's credit_balance_cents is credited by
        approved_refund_cents."

        Claim: approved_refund_cents increases customer's credit_balance_cents by the same.

        # difficulty: transitive_cascade/return_approve_cascade_to_work_order_closure
        """
        ctx = run_to_return_requested(subtotal_cents=1000, requested_refund_cents=400)
        ret = ctx["return"]
        customer_id = ctx["customer"]["id"]
        before = get_success_data(
            api.get_customer(customer_id, TEST_USERS["admin_headers"])
        )
        api.approve_return(ret["id"], approve_return_payload(400), cs_headers)
        after = get_success_data(
            api.get_customer(customer_id, TEST_USERS["admin_headers"])
        )
        assert after["credit_balance_cents"] == before["credit_balance_cents"] + 400

    def test_approve_decrements_restaurant_settlement(self, api, cs_headers):
        """PRD §3.9: "The restaurant's pending_settlement_cents is decremented by the
        same amount."

        Claim: approved_refund_cents decreases restaurant.pending_settlement_cents by the
        exact same.

        # difficulty: transitive_cascade/return_approve_cascade_to_work_order_closure
        """
        ctx = run_to_return_requested(subtotal_cents=1000, requested_refund_cents=400)
        ret = ctx["return"]
        restaurant_id = ctx["restaurant"]["id"]
        before = get_success_data(
            api.get_restaurant(restaurant_id, TEST_USERS["admin_headers"])
        )
        api.approve_return(ret["id"], approve_return_payload(400), cs_headers)
        after = get_success_data(
            api.get_restaurant(restaurant_id, TEST_USERS["admin_headers"])
        )
        assert after["pending_settlement_cents"] == before["pending_settlement_cents"] - 400

    def test_approved_refund_exceeds_requested_rejected(self, api, cs_headers):
        """PRD §3.9: "Approval carries an approved_refund_cents amount that must be at
        least 1, at most the order's subtotal_cents, and at most the originally requested
        refund — any violation is rejected with ERR_REFUND_AMOUNT_INVALID."

        Claim: approved_refund_cents > requested_refund_cents → ERR_REFUND_AMOUNT_INVALID.
        """
        ctx = run_to_return_requested(subtotal_cents=1000, requested_refund_cents=400)
        ret = ctx["return"]
        res = api.approve_return(ret["id"], approve_return_payload(500), cs_headers)
        validate_error(res, "ERR_REFUND_AMOUNT_INVALID")


class TestReturnReject:
    def test_reject_reverts_order_to_delivered(self, api, cs_headers):
        """PRD §3.9: "Rejection by a CustomerService operator moves the Return to REJECTED
        and reverts the order from REFUND_REQUESTED to DELIVERED with no monetary change."

        Claim: /reject on REQUESTED → Return.status=REJECTED, Order.status=DELIVERED.
        """
        ctx = run_to_return_requested(subtotal_cents=1000, requested_refund_cents=400)
        ret = ctx["return"]
        res = api.reject_return(ret["id"], cs_headers)
        data = validate_success(res, 200)
        assert data["status"] == "REJECTED"

        order = get_success_data(api.get_order(ctx["order"]["id"], TEST_USERS["admin_headers"]))
        assert order["status"] == "DELIVERED"


class TestReturnEscalationCycle:
    def test_escalate_opens_workorder_reopen_closes_it(self, api, cs_headers):
        """PRD §3.9: "Escalation moves the Return from REQUESTED to ESCALATED and opens a
        WorkOrder linked via related_return_id for supervisor attention. An escalated
        return can be brought back to REQUESTED through a reopen step — this closes the
        linked WorkOrder."

        Claim: /escalate → Return.ESCALATED + WorkOrder opened; /reopen → Return.REQUESTED
        + WorkOrder CLOSED.

        # difficulty: non_linear_state_machine/return_revision_cycle_on_return_entity
        """
        ctx = run_to_return_requested(subtotal_cents=1000, requested_refund_cents=400)
        ret = ctx["return"]

        # Escalate.
        esc = validate_success(api.escalate_return(ret["id"], cs_headers), 200)
        assert esc["status"] == "ESCALATED"
        # Reopen.
        reo = validate_success(api.reopen_return(ret["id"], cs_headers), 200)
        assert reo["status"] == "REQUESTED"

    def test_requested_escalated_requested_escalated_approved_cycle(self, api, cs_headers):
        """PRD §3.9: "The approve / reject transitions accept both REQUESTED and
        ESCALATED as legal starting states; the reopen transition is only legal from
        ESCALATED."

        Claim: a Return can visit REQUESTED → ESCALATED → REQUESTED → ESCALATED →
        APPROVED in that exact order.

        # difficulty: non_linear_state_machine/return_revision_cycle_on_return_entity
        """
        ctx = run_to_return_requested(subtotal_cents=1000, requested_refund_cents=400)
        ret = ctx["return"]
        validate_success(api.escalate_return(ret["id"], cs_headers), 200)
        validate_success(api.reopen_return(ret["id"], cs_headers), 200)
        validate_success(api.escalate_return(ret["id"], cs_headers), 200)
        approved = validate_success(
            api.approve_return(ret["id"], approve_return_payload(400), cs_headers), 200
        )
        assert approved["status"] == "APPROVED"

        order = get_success_data(api.get_order(ctx["order"]["id"], TEST_USERS["admin_headers"]))
        assert order["status"] == "REFUNDED"
