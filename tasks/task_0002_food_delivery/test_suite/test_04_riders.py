"""Tests for rider CRUD, onboarding, state transitions, and penalty framework.

Covers: PRD Section 3.9 (Rider Onboarding), 3.10 (Suspension/Deactivation),
2.10 (Penalty Framework), Table 2 (Rider state machine), Table 6 (errors).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_rider, create_rider_payload,
    create_and_approve_rider,
    setup_basic_order_scenario, confirm_order, prepare_order,
    mark_order_ready, assign_rider_to_order,
    progress_delivery_to_restaurant, create_delivery_payload,
    SUSPENSION_THRESHOLD, CANCELLATION_POINTS,
)


_admin = TEST_USERS["admin_headers"]
_rider = TEST_USERS["rider_headers"]
_customer = TEST_USERS["customer_headers"]


class TestRiderCreation:
    """PRD 3.9: platform_admin registers riders."""

    def test_create_rider_success(self):
        """Create rider with PENDING_APPROVAL status and default max_concurrent_deliveries=3."""
        payload = create_rider_payload(vehicle_type="BICYCLE")
        resp = api_client.create_rider(payload, _admin)
        data = validate_success(resp, 201)
        assert_rider(data)
        assert data["status"] == "PENDING_APPROVAL"
        assert data["max_concurrent_deliveries"] == 3
        assert data["active_delivery_count"] == 0
        assert data["penalty_points"] == 0
        assert data["cancellation_count"] == 0
        assert data["earnings_balance_cents"] == 0

    def test_create_rider_custom_max_concurrent(self):
        """Specify max_concurrent_deliveries at creation."""
        payload = create_rider_payload(max_concurrent_deliveries=5)
        resp = api_client.create_rider(payload, _admin)
        data = validate_success(resp, 201)
        assert data["max_concurrent_deliveries"] == 5

    def test_duplicate_rider_phone_rejected(self):
        """Duplicate phone among riders triggers ERR_DUPLICATE_PHONE."""
        phone = "+16669999999"
        get_success_data(api_client.create_rider(create_rider_payload(phone=phone), _admin))
        resp = api_client.create_rider(create_rider_payload(phone=phone), _admin)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PHONE)

    def test_create_rider_forbidden_for_customer(self):
        """Only platform_admin can register riders."""
        resp = api_client.create_rider(create_rider_payload(), _customer)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestRiderStateTransitions:
    """PRD 3.9–3.10 + Table 2: Rider state machine."""

    def test_approve_pending_rider(self):
        """PENDING_APPROVAL -> ACTIVE."""
        payload = create_rider_payload()
        r = get_success_data(api_client.create_rider(payload, _admin))
        resp = api_client.approve_rider(r["id"], _admin)
        data = validate_success(resp)
        assert data["status"] == "ACTIVE"

    def test_suspend_active_rider(self):
        """ACTIVE -> SUSPENDED, is_online forced to false."""
        rider = create_and_approve_rider()
        resp = api_client.suspend_rider(rider["id"], _admin)
        data = validate_success(resp)
        assert data["status"] == "SUSPENDED"
        assert data["is_online"] is False

    def test_reinstate_suspended_rider_resets_penalty(self):
        """SUSPENDED -> ACTIVE, penalty_points reset to 0 (PRD 3.10)."""
        rider = create_and_approve_rider()
        get_success_data(api_client.suspend_rider(rider["id"], _admin))
        resp = api_client.reinstate_rider(rider["id"], _admin)
        data = validate_success(resp)
        assert data["status"] == "ACTIVE"
        assert data["penalty_points"] == 0

    def test_deactivate_active_rider_no_deliveries(self):
        """ACTIVE -> DEACTIVATED when no active deliveries."""
        rider = create_and_approve_rider()
        resp = api_client.deactivate_rider(rider["id"], _admin)
        data = validate_success(resp)
        assert data["status"] == "DEACTIVATED"
        assert data["is_online"] is False

    def test_deactivate_active_rider_with_deliveries_blocked(self):
        """Cannot deactivate ACTIVE rider with active deliveries (ERR_ACTIVE_DELIVERIES_EXIST)."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        rider = create_and_approve_rider()
        confirm_order(order["id"])
        assign_rider_to_order(order["id"], rider["id"])

        resp = api_client.deactivate_rider(rider["id"], _admin)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_DELIVERIES_EXIST)

    def test_deactivate_suspended_rider(self):
        """SUSPENDED -> DEACTIVATED (no preconditions)."""
        rider = create_and_approve_rider()
        get_success_data(api_client.suspend_rider(rider["id"], _admin))
        resp = api_client.deactivate_rider(rider["id"], _admin)
        data = validate_success(resp)
        assert data["status"] == "DEACTIVATED"

    @pytest.mark.parametrize("invalid_from", ["PENDING_APPROVAL", "DEACTIVATED"])
    def test_cannot_suspend_from_invalid_state(self, invalid_from):
        """Suspend only valid from ACTIVE."""
        payload = create_rider_payload()
        r = get_success_data(api_client.create_rider(payload, _admin))
        if invalid_from == "DEACTIVATED":
            get_success_data(api_client.approve_rider(r["id"], _admin))
            get_success_data(api_client.update_rider(r["id"], {"is_online": True}, _rider))
            get_success_data(api_client.deactivate_rider(r["id"], _admin))
        resp = api_client.suspend_rider(r["id"], _admin)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestRiderUpdate:
    """PRD 3.9: Rider updates location and online status."""

    def test_update_rider_location(self):
        """Update current_latitude and current_longitude."""
        rider = create_and_approve_rider()
        resp = api_client.update_rider(
            rider["id"],
            {"current_latitude": 40.75, "current_longitude": -73.98},
            _rider,
        )
        data = validate_success(resp)
        assert data["current_latitude"] == pytest.approx(40.75, abs=0.001)
        assert data["current_longitude"] == pytest.approx(-73.98, abs=0.001)

    def test_update_rider_online_status(self):
        """Toggle is_online."""
        rider = create_and_approve_rider()
        resp = api_client.update_rider(rider["id"], {"is_online": False}, _rider)
        data = validate_success(resp)
        assert data["is_online"] is False

    def test_rider_not_found(self):
        """Non-existent rider returns ERR_RIDER_NOT_FOUND."""
        resp = api_client.get_rider(NON_EXISTENT_UUID, _admin)
        validate_error(resp, ApiErrorId.ERR_RIDER_NOT_FOUND)


class TestRiderSuspensionCascade:
    """PRD 3.10: Side effects of rider suspension on deliveries."""

    def test_suspension_cancels_assigned_deliveries(self):
        """Suspending a rider cancels ASSIGNED deliveries and reverts orders."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        rider = create_and_approve_rider()
        order = confirm_order(order["id"])
        delivery = assign_rider_to_order(order["id"], rider["id"])
        assert delivery["status"] == "ASSIGNED"

        get_success_data(api_client.suspend_rider(rider["id"], _admin))

        # Delivery should be CANCELLED_BY_RIDER
        d = get_success_data(api_client.get_delivery(order["id"], delivery["id"], _admin))
        assert d["status"] == "CANCELLED_BY_RIDER"

    def test_suspension_penalty_per_cancelled_delivery(self):
        """Each cancelled delivery during suspension accrues 15 penalty points (PRD 3.10)."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        rider = create_and_approve_rider()
        order = confirm_order(order["id"])
        assign_rider_to_order(order["id"], rider["id"])

        suspended = get_success_data(api_client.suspend_rider(rider["id"], _admin))
        # 1 delivery cancelled -> 15 points
        assert suspended["penalty_points"] == 15
