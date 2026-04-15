"""Tests for rider penalty framework, auto-suspension, and cancellation rate.

Covers: PRD Section 2.10 (Rider Discipline and Penalty Framework),
Table 3 (rider_penalty_scoring, rider_cancellation_rate).
"""
import math
import pytest
from decimal import Decimal, ROUND_HALF_UP
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_and_approve_rider, setup_basic_order_scenario,
    confirm_order, assign_rider_to_order, create_delivery_payload,
    LATE_DELIVERY_POINTS, CANCELLATION_POINTS, COMPLAINT_UPHELD_POINTS,
    NO_SHOW_POINTS, SUSPENSION_THRESHOLD,
)


_admin = TEST_USERS["admin_headers"]
_rider = TEST_USERS["rider_headers"]


class TestPenaltyPoints:
    """PRD 2.10: Penalty points per infraction type."""

    def test_cancellation_accrues_20_points(self):
        """Delivery cancellation by rider: +20 penalty points."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        rider = create_and_approve_rider()
        confirm_order(order["id"])
        delivery = assign_rider_to_order(order["id"], rider["id"])

        get_success_data(api_client.cancel_delivery(order["id"], delivery["id"], _rider))

        r = get_success_data(api_client.get_rider(rider["id"], _admin))
        assert r["penalty_points"] == CANCELLATION_POINTS, \
            f"Expected {CANCELLATION_POINTS} penalty points, got {r['penalty_points']}"

    def test_multiple_cancellations_accumulate(self):
        """Multiple cancellations accumulate penalty points."""
        rider = create_and_approve_rider()

        for i in range(3):
            rest, menu_items, customer, order = setup_basic_order_scenario()
            confirm_order(order["id"])
            delivery = assign_rider_to_order(order["id"], rider["id"])
            get_success_data(api_client.cancel_delivery(order["id"], delivery["id"], _rider))

        r = get_success_data(api_client.get_rider(rider["id"], _admin))
        assert r["penalty_points"] == CANCELLATION_POINTS * 3, \
            f"Expected {CANCELLATION_POINTS * 3} penalty points after 3 cancellations"
        assert r["cancellation_count"] == 3


class TestAutoSuspension:
    """PRD 2.10: Auto-suspension when penalty_points >= 100."""

    def test_auto_suspension_at_threshold(self):
        """Rider auto-suspended when penalty reaches 100 (5 cancellations = 100 points)."""
        rider = create_and_approve_rider()

        for i in range(5):
            rest, menu_items, customer, order = setup_basic_order_scenario()
            confirm_order(order["id"])
            delivery = assign_rider_to_order(order["id"], rider["id"])
            get_success_data(api_client.cancel_delivery(order["id"], delivery["id"], _rider))
            # After 5th cancellation: 5 * 20 = 100 points -> auto-suspend
            r = get_success_data(api_client.get_rider(rider["id"], _admin))
            if r["status"] == "SUSPENDED":
                break
            # If not suspended yet, rider may need to be set online again
            if r["status"] == "ACTIVE":
                get_success_data(api_client.update_rider(rider["id"], {"is_online": True}, _rider))

        r = get_success_data(api_client.get_rider(rider["id"], _admin))
        assert r["status"] == "SUSPENDED", \
            f"Rider should be SUSPENDED at {SUSPENSION_THRESHOLD} points, got status={r['status']}"
        assert r["penalty_points"] >= SUSPENSION_THRESHOLD

    def test_below_threshold_not_suspended(self):
        """Rider with < 100 points remains ACTIVE."""
        rider = create_and_approve_rider()
        # 4 cancellations = 80 points (below threshold)
        for i in range(4):
            rest, menu_items, customer, order = setup_basic_order_scenario()
            confirm_order(order["id"])
            delivery = assign_rider_to_order(order["id"], rider["id"])
            get_success_data(api_client.cancel_delivery(order["id"], delivery["id"], _rider))
            r = get_success_data(api_client.get_rider(rider["id"], _admin))
            if r["status"] == "ACTIVE":
                get_success_data(api_client.update_rider(rider["id"], {"is_online": True}, _rider))

        r = get_success_data(api_client.get_rider(rider["id"], _admin))
        assert r["penalty_points"] == 80
        assert r["status"] == "ACTIVE"

    def test_reinstatement_resets_penalty_points(self):
        """Reinstatement resets penalty_points to 0 (PRD 2.10)."""
        rider = create_and_approve_rider()
        # Suspend via admin
        get_success_data(api_client.suspend_rider(rider["id"], _admin))
        get_success_data(api_client.reinstate_rider(rider["id"], _admin))
        r = get_success_data(api_client.get_rider(rider["id"], _admin))
        assert r["penalty_points"] == 0
        assert r["status"] == "ACTIVE"


class TestCancellationRate:
    """PRD 3.9: cancellation_rate = cancellation_count / (total_deliveries_completed + cancellation_count).

    Table 3 (rider_cancellation_rate): 4 decimal places, round half up.
    """

    def test_cancellation_rate_after_cancellation(self):
        """Rate calculated correctly after a cancellation (0 completions, 1 cancel)."""
        rider = create_and_approve_rider()
        rest, menu_items, customer, order = setup_basic_order_scenario()
        confirm_order(order["id"])
        delivery = assign_rider_to_order(order["id"], rider["id"])
        get_success_data(api_client.cancel_delivery(order["id"], delivery["id"], _rider))

        r = get_success_data(api_client.get_rider(rider["id"], _admin))
        # cancellation_count=1, total_deliveries_completed=0
        # rate = 1 / (0 + 1) = 1.0
        assert r["cancellation_rate"] == pytest.approx(1.0, abs=0.0001)

    def test_cancellation_rate_zero_when_no_events(self):
        """Rate is 0.0 when no deliveries and no cancellations."""
        rider = create_and_approve_rider()
        r = get_success_data(api_client.get_rider(rider["id"], _admin))
        assert r["cancellation_rate"] == pytest.approx(0.0, abs=0.0001)
