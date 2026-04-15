"""Tests for complaint filing, assignment, escalation, and resolution.

Covers: PRD Section 3.13 (Complaints and Resolution), Table 2 (Complaint state machine),
Table 6 (complaint errors).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_complaint, create_complaint_payload,
    create_resolve_complaint_payload,
    complete_order_lifecycle, setup_delivered_order_for_complaint,
    setup_basic_order_scenario, confirm_order,
    create_active_customer, create_top_up_payload,
    COMPLAINT_UPHELD_POINTS, MAX_COMPLAINTS_PER_ORDER,
)


_admin = TEST_USERS["admin_headers"]
_customer = TEST_USERS["customer_headers"]
_restaurant = TEST_USERS["restaurant_headers"]
_rider = TEST_USERS["rider_headers"]
_cs = TEST_USERS["cs_headers"]


class TestComplaintFiling:
    """PRD 3.13: Filing complaints on delivered or cancelled orders."""

    def test_file_complaint_on_delivered_order(self):
        """Complaint created in FILED status on a DELIVERED order."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_complaint()
        payload = create_complaint_payload("CUSTOMER", customer["id"])
        resp = api_client.create_complaint(order["id"], payload, _customer)
        data = validate_success(resp, 201)
        assert_complaint(data)
        assert data["status"] == "FILED"
        assert data["filed_by"] == "CUSTOMER"
        assert data["order_id"] == order["id"]

    def test_file_complaint_on_cancelled_order(self):
        """Complaints can be filed on cancelled orders."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        # Cancel the order
        get_success_data(api_client.cancel_order(order["id"], _customer))
        payload = create_complaint_payload("CUSTOMER", customer["id"])
        resp = api_client.create_complaint(order["id"], payload, _customer)
        data = validate_success(resp, 201)
        assert data["status"] == "FILED"

    def test_complaint_on_non_eligible_order(self):
        """ERR_ORDER_NOT_ELIGIBLE_FOR_COMPLAINT when order is still in progress."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        confirm_order(order["id"])
        payload = create_complaint_payload("CUSTOMER", customer["id"])
        resp = api_client.create_complaint(order["id"], payload, _customer)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_ELIGIBLE_FOR_COMPLAINT)

    def test_max_complaints_per_order(self):
        """ERR_MAX_COMPLAINTS_REACHED when 2 complaints already filed."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_complaint()
        for i in range(MAX_COMPLAINTS_PER_ORDER):
            payload = create_complaint_payload("CUSTOMER", customer["id"], category="WRONG_ITEMS")
            get_success_data(api_client.create_complaint(order["id"], payload, _customer))

        # Third complaint should fail
        payload = create_complaint_payload("CUSTOMER", customer["id"], category="COLD_FOOD")
        resp = api_client.create_complaint(order["id"], payload, _customer)
        validate_error(resp, ApiErrorId.ERR_MAX_COMPLAINTS_REACHED)

    @pytest.mark.parametrize("category", [
        "WRONG_ITEMS", "MISSING_ITEMS", "COLD_FOOD", "LATE_DELIVERY",
        "RUDE_BEHAVIOR", "DAMAGED_PACKAGING", "OTHER"
    ])
    def test_all_complaint_categories(self, category):
        """All 7 complaint categories are accepted."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_complaint()
        payload = create_complaint_payload("CUSTOMER", customer["id"], category=category)
        resp = api_client.create_complaint(order["id"], payload, _customer)
        data = validate_success(resp, 201)
        assert data["category"] == category


class TestComplaintWorkflow:
    """PRD 3.13: Complaint state transitions — assign, escalate, resolve."""

    def test_assign_complaint(self):
        """FILED -> UNDER_REVIEW, assigned_agent_id set."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_complaint()
        complaint = get_success_data(api_client.create_complaint(
            order["id"], create_complaint_payload("CUSTOMER", customer["id"]), _customer
        ))
        resp = api_client.assign_complaint(
            order["id"], complaint["id"],
            {"assigned_agent_id": "agent-1"}, _cs
        )
        data = validate_success(resp)
        assert data["status"] == "UNDER_REVIEW"
        assert data["assigned_agent_id"] == "agent-1"

    def test_escalate_complaint(self):
        """UNDER_REVIEW -> ESCALATED."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_complaint()
        complaint = get_success_data(api_client.create_complaint(
            order["id"], create_complaint_payload("CUSTOMER", customer["id"]), _customer
        ))
        get_success_data(api_client.assign_complaint(
            order["id"], complaint["id"],
            {"assigned_agent_id": "agent-1"}, _cs
        ))
        resp = api_client.escalate_complaint(order["id"], complaint["id"], _cs)
        data = validate_success(resp)
        assert data["status"] == "ESCALATED"

    def test_escalated_can_be_reassigned(self):
        """ESCALATED -> UNDER_REVIEW (cyclic path, by platform_admin)."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_complaint()
        complaint = get_success_data(api_client.create_complaint(
            order["id"], create_complaint_payload("CUSTOMER", customer["id"]), _customer
        ))
        get_success_data(api_client.assign_complaint(
            order["id"], complaint["id"],
            {"assigned_agent_id": "agent-1"}, _cs
        ))
        get_success_data(api_client.escalate_complaint(order["id"], complaint["id"], _cs))

        resp = api_client.assign_complaint(
            order["id"], complaint["id"],
            {"assigned_agent_id": "agent-2"}, _admin
        )
        data = validate_success(resp)
        assert data["status"] == "UNDER_REVIEW"
        assert data["assigned_agent_id"] == "agent-2"

    def test_cannot_escalate_filed_complaint(self):
        """Cannot escalate a FILED complaint (must be UNDER_REVIEW first)."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_complaint()
        complaint = get_success_data(api_client.create_complaint(
            order["id"], create_complaint_payload("CUSTOMER", customer["id"]), _customer
        ))
        resp = api_client.escalate_complaint(order["id"], complaint["id"], _cs)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestComplaintResolution:
    """PRD 3.13: Resolution types — refund, credit, no action."""

    def test_resolve_with_refund(self):
        """UNDER_REVIEW -> RESOLVED_REFUND; wallet credited, payment_status updated."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_complaint()
        complaint = get_success_data(api_client.create_complaint(
            order["id"], create_complaint_payload("CUSTOMER", customer["id"]), _customer
        ))
        get_success_data(api_client.assign_complaint(
            order["id"], complaint["id"],
            {"assigned_agent_id": "agent-1"}, _cs
        ))
        amount = order["total_cents"]  # full refund
        resp = api_client.resolve_complaint(
            order["id"], complaint["id"],
            create_resolve_complaint_payload("REFUND", amount), _cs
        )
        data = validate_success(resp)
        assert data["status"] == "RESOLVED_REFUND"
        assert data["resolution_amount_cents"] == amount

        # Order payment_status should be REFUNDED (full refund)
        refreshed_order = get_success_data(api_client.get_order(order["id"], _admin))
        assert refreshed_order["payment_status"] == "REFUNDED"

    def test_resolve_with_partial_refund(self):
        """Partial refund: payment_status -> PARTIALLY_REFUNDED."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_complaint()
        complaint = get_success_data(api_client.create_complaint(
            order["id"], create_complaint_payload("CUSTOMER", customer["id"]), _customer
        ))
        get_success_data(api_client.assign_complaint(
            order["id"], complaint["id"],
            {"assigned_agent_id": "agent-1"}, _cs
        ))
        amount = order["total_cents"] // 2  # partial
        resp = api_client.resolve_complaint(
            order["id"], complaint["id"],
            create_resolve_complaint_payload("REFUND", amount), _cs
        )
        data = validate_success(resp)
        assert data["status"] == "RESOLVED_REFUND"

        refreshed_order = get_success_data(api_client.get_order(order["id"], _admin))
        assert refreshed_order["payment_status"] == "PARTIALLY_REFUNDED"

    def test_resolve_with_credit(self):
        """UNDER_REVIEW -> RESOLVED_CREDIT; wallet credited via CREDIT transaction."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_complaint()
        complaint = get_success_data(api_client.create_complaint(
            order["id"], create_complaint_payload("CUSTOMER", customer["id"]), _customer
        ))
        get_success_data(api_client.assign_complaint(
            order["id"], complaint["id"],
            {"assigned_agent_id": "agent-1"}, _cs
        ))
        resp = api_client.resolve_complaint(
            order["id"], complaint["id"],
            create_resolve_complaint_payload("CREDIT", 500), _cs
        )
        data = validate_success(resp)
        assert data["status"] == "RESOLVED_CREDIT"

    def test_resolve_no_action(self):
        """UNDER_REVIEW -> RESOLVED_NO_ACTION; no financial adjustment."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_complaint()
        wallet_before = get_success_data(
            api_client.get_customer(customer["id"], _admin)
        )["wallet_balance_cents"]

        complaint = get_success_data(api_client.create_complaint(
            order["id"], create_complaint_payload("CUSTOMER", customer["id"]), _customer
        ))
        get_success_data(api_client.assign_complaint(
            order["id"], complaint["id"],
            {"assigned_agent_id": "agent-1"}, _cs
        ))
        resp = api_client.resolve_complaint(
            order["id"], complaint["id"],
            create_resolve_complaint_payload("NO_ACTION"), _cs
        )
        data = validate_success(resp)
        assert data["status"] == "RESOLVED_NO_ACTION"

        wallet_after = get_success_data(
            api_client.get_customer(customer["id"], _admin)
        )["wallet_balance_cents"]
        assert wallet_after == wallet_before

    def test_resolution_exceeds_order_total(self):
        """ERR_RESOLUTION_EXCEEDS_ORDER when amount > total_cents."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_complaint()
        complaint = get_success_data(api_client.create_complaint(
            order["id"], create_complaint_payload("CUSTOMER", customer["id"]), _customer
        ))
        get_success_data(api_client.assign_complaint(
            order["id"], complaint["id"],
            {"assigned_agent_id": "agent-1"}, _cs
        ))
        resp = api_client.resolve_complaint(
            order["id"], complaint["id"],
            create_resolve_complaint_payload("REFUND", order["total_cents"] + 1), _cs
        )
        validate_error(resp, ApiErrorId.ERR_RESOLUTION_EXCEEDS_ORDER)

    def test_resolve_from_escalated(self):
        """ESCALATED -> RESOLVED_REFUND (by platform_admin)."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_complaint()
        complaint = get_success_data(api_client.create_complaint(
            order["id"], create_complaint_payload("CUSTOMER", customer["id"]), _customer
        ))
        get_success_data(api_client.assign_complaint(
            order["id"], complaint["id"],
            {"assigned_agent_id": "agent-1"}, _cs
        ))
        get_success_data(api_client.escalate_complaint(order["id"], complaint["id"], _cs))

        resp = api_client.resolve_complaint(
            order["id"], complaint["id"],
            create_resolve_complaint_payload("REFUND", 500), _admin
        )
        data = validate_success(resp)
        assert data["status"] == "RESOLVED_REFUND"

    def test_complaint_not_found(self):
        """ERR_COMPLAINT_NOT_FOUND for non-existent complaint."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_complaint()
        resp = api_client.assign_complaint(
            order["id"], NON_EXISTENT_UUID,
            {"assigned_agent_id": "agent-1"}, _cs
        )
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_FOUND)

    def test_refund_complaint_rider_penalty(self):
        """Full refund complaint against rider: +15 penalty points (COMPLAINT_UPHELD)."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_complaint()
        rider_before = get_success_data(api_client.get_rider(rider["id"], _admin))
        initial_penalty = rider_before["penalty_points"]

        complaint = get_success_data(api_client.create_complaint(
            order["id"],
            create_complaint_payload("CUSTOMER", customer["id"], category="RUDE_BEHAVIOR"),
            _customer,
        ))
        get_success_data(api_client.assign_complaint(
            order["id"], complaint["id"],
            {"assigned_agent_id": "agent-1"}, _cs
        ))
        get_success_data(api_client.resolve_complaint(
            order["id"], complaint["id"],
            create_resolve_complaint_payload("REFUND", order["total_cents"]), _cs
        ))

        rider_after = get_success_data(api_client.get_rider(rider["id"], _admin))
        assert rider_after["penalty_points"] == initial_penalty + COMPLAINT_UPHELD_POINTS, \
            f"Expected penalty increase of {COMPLAINT_UPHELD_POINTS}"
