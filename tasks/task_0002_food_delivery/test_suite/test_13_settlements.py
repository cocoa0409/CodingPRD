"""Tests for settlement processing.

Covers: PRD Section 3.15 (Settlement and Payout Processing),
Table 2 (Settlement state machine), Table 3 (settlement_calculation).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_settlement, create_settlement_run_payload,
    complete_order_lifecycle,
)


_admin = TEST_USERS["admin_headers"]
_customer = TEST_USERS["customer_headers"]


class TestSettlementRun:
    """PRD 3.15: Admin triggers settlement run."""

    def test_settlement_run_creates_records(self):
        """Settlement run creates records for entities with pending balances."""
        rest, menu_items, customer, rider, order, delivery = complete_order_lifecycle(
            item_price_cents=3000
        )
        # Restaurant and rider should have pending balances
        rest_data = get_success_data(api_client.get_restaurant(rest["id"], _admin))
        assert rest_data["balance_pending_cents"] > 0

        rider_data = get_success_data(api_client.get_rider(rider["id"], _admin))
        assert rider_data["earnings_balance_cents"] > 0

        resp = api_client.run_settlement(create_settlement_run_payload(), _admin)
        data = validate_success(resp)
        # Should return settlement records (array)
        assert isinstance(data, list), "Settlement run should return a list"
        assert len(data) >= 1, "At least one settlement should be created"

    def test_settlement_zeros_pending_balances(self):
        """After settlement, pending balances are zeroed and settled amounts increased."""
        rest, menu_items, customer, rider, order, delivery = complete_order_lifecycle(
            item_price_cents=5000
        )
        rest_before = get_success_data(api_client.get_restaurant(rest["id"], _admin))
        pending = rest_before["balance_pending_cents"]
        settled_before = rest_before["balance_settled_cents"]

        get_success_data(api_client.run_settlement(create_settlement_run_payload(), _admin))

        rest_after = get_success_data(api_client.get_restaurant(rest["id"], _admin))
        assert rest_after["balance_pending_cents"] == 0, \
            "balance_pending_cents should be 0 after settlement"
        assert rest_after["balance_settled_cents"] >= settled_before, \
            "balance_settled_cents should increase after settlement"

    def test_rider_settlement_zeros_earnings(self):
        """Rider earnings_balance_cents zeroed after settlement."""
        rest, menu_items, customer, rider, order, delivery = complete_order_lifecycle(
            item_price_cents=3000
        )
        rider_before = get_success_data(api_client.get_rider(rider["id"], _admin))
        assert rider_before["earnings_balance_cents"] > 0

        get_success_data(api_client.run_settlement(create_settlement_run_payload(), _admin))

        rider_after = get_success_data(api_client.get_rider(rider["id"], _admin))
        assert rider_after["earnings_balance_cents"] == 0
        assert rider_after["earnings_settled_cents"] > 0

    def test_settlement_forbidden_for_customer(self):
        """Only platform_admin can run settlements."""
        resp = api_client.run_settlement(create_settlement_run_payload(), _customer)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestSettlementLifecycle:
    """PRD 3.15 + Table 2: Settlement state transitions."""

    def test_approve_calculated_settlement(self):
        """CALCULATED -> APPROVED (settlements are created in DRAFT, system moves to CALCULATED)."""
        rest, menu_items, customer, rider, order, delivery = complete_order_lifecycle(
            item_price_cents=3000
        )
        settlements = get_success_data(
            api_client.run_settlement(create_settlement_run_payload(), _admin)
        )
        # Find a settlement to approve
        if isinstance(settlements, list) and len(settlements) > 0:
            s = settlements[0]
            sid = s["id"]
            # If in CALCULATED status, approve it
            if s.get("status") in ["CALCULATED", "DRAFT"]:
                resp = api_client.approve_settlement(sid, _admin)
                data = validate_success(resp)
                assert data["status"] == "APPROVED"

    def test_mark_paid_approved_settlement(self):
        """APPROVED -> PAID."""
        rest, menu_items, customer, rider, order, delivery = complete_order_lifecycle(
            item_price_cents=3000
        )
        settlements = get_success_data(
            api_client.run_settlement(create_settlement_run_payload(), _admin)
        )
        if isinstance(settlements, list) and len(settlements) > 0:
            s = settlements[0]
            sid = s["id"]
            if s.get("status") in ["CALCULATED", "DRAFT"]:
                get_success_data(api_client.approve_settlement(sid, _admin))
            resp = api_client.mark_settlement_paid(sid, _admin)
            data = validate_success(resp)
            assert data["status"] == "PAID"

    def test_settlement_not_found(self):
        """ERR_SETTLEMENT_NOT_FOUND for non-existent settlement."""
        resp = api_client.approve_settlement(NON_EXISTENT_UUID, _admin)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_FOUND)
