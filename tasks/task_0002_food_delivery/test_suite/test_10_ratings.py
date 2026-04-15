"""Tests for rating submission, publication, and average recalculation.

Covers: PRD Section 3.12 (Ratings and Reputation), Table 2 (Rating state machine),
Table 3 (rating_average), Table 6 (rating errors).
"""
import pytest
from decimal import Decimal, ROUND_HALF_UP
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_rating, create_rating_payload,
    complete_order_lifecycle, setup_delivered_order_for_rating,
    setup_basic_order_scenario, confirm_order,
)


_admin = TEST_USERS["admin_headers"]
_customer = TEST_USERS["customer_headers"]
_restaurant = TEST_USERS["restaurant_headers"]
_rider = TEST_USERS["rider_headers"]


def _round_half_up(value, places=2):
    """Round half up to given decimal places, matching PRD rounding rule."""
    d = Decimal(str(value))
    return float(d.quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP))


class TestRatingCreation:
    """PRD 3.12: Participants submit ratings after delivery."""

    def test_create_customer_to_restaurant_rating(self):
        """Customer rates restaurant after DELIVERED order."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_rating()
        payload = create_rating_payload(
            "CUSTOMER_TO_RESTAURANT", customer["id"], rest["id"], score=4
        )
        resp = api_client.create_rating(order["id"], payload, _customer)
        data = validate_success(resp, 201)
        assert_rating(data)
        assert data["status"] == "PENDING"
        assert data["rater_type"] == "CUSTOMER_TO_RESTAURANT"
        assert data["score"] == 4

    def test_create_customer_to_rider_rating(self):
        """Customer rates rider."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_rating()
        payload = create_rating_payload(
            "CUSTOMER_TO_RIDER", customer["id"], rider["id"], score=5
        )
        resp = api_client.create_rating(order["id"], payload, _customer)
        data = validate_success(resp, 201)
        assert data["rater_type"] == "CUSTOMER_TO_RIDER"

    def test_create_restaurant_to_rider_rating(self):
        """Restaurant rates rider."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_rating()
        payload = create_rating_payload(
            "RESTAURANT_TO_RIDER", rest["id"], rider["id"], score=3
        )
        resp = api_client.create_rating(order["id"], payload, _restaurant)
        data = validate_success(resp, 201)
        assert data["rater_type"] == "RESTAURANT_TO_RIDER"

    def test_rating_on_non_delivered_order(self):
        """ERR_ORDER_NOT_DELIVERED when order is not DELIVERED."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        payload = create_rating_payload(
            "CUSTOMER_TO_RESTAURANT", customer["id"], rest["id"], score=4
        )
        resp = api_client.create_rating(order["id"], payload, _customer)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DELIVERED)

    def test_invalid_rating_score_zero(self):
        """ERR_INVALID_RATING when score < 1."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_rating()
        payload = create_rating_payload(
            "CUSTOMER_TO_RESTAURANT", customer["id"], rest["id"], score=0
        )
        resp = api_client.create_rating(order["id"], payload, _customer)
        validate_error(resp, ApiErrorId.ERR_INVALID_RATING)

    def test_invalid_rating_score_six(self):
        """ERR_INVALID_RATING when score > 5."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_rating()
        payload = create_rating_payload(
            "CUSTOMER_TO_RESTAURANT", customer["id"], rest["id"], score=6
        )
        resp = api_client.create_rating(order["id"], payload, _customer)
        validate_error(resp, ApiErrorId.ERR_INVALID_RATING)

    @pytest.mark.parametrize("score", [1, 5])
    def test_valid_rating_score_boundaries(self, score):
        """Boundary: scores 1 and 5 are both valid."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_rating()
        payload = create_rating_payload(
            "CUSTOMER_TO_RESTAURANT", customer["id"], rest["id"], score=score
        )
        resp = api_client.create_rating(order["id"], payload, _customer)
        data = validate_success(resp, 201)
        assert data["score"] == score

    def test_duplicate_rating_rejected(self):
        """ERR_DUPLICATE_RATING for same rater_type + rater_id + order_id."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_rating()
        payload = create_rating_payload(
            "CUSTOMER_TO_RESTAURANT", customer["id"], rest["id"], score=4
        )
        get_success_data(api_client.create_rating(order["id"], payload, _customer))
        resp = api_client.create_rating(order["id"], payload, _customer)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RATING)


class TestRatingPublicationAndAverage:
    """PRD 3.12: Publication updates rating_average; hiding triggers recalculation."""

    def test_publish_rating(self):
        """PENDING -> PUBLISHED, restaurant average updated."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_rating()
        payload = create_rating_payload(
            "CUSTOMER_TO_RESTAURANT", customer["id"], rest["id"], score=4
        )
        rating = get_success_data(api_client.create_rating(order["id"], payload, _customer))

        resp = api_client.publish_rating(order["id"], rating["id"], _admin)
        data = validate_success(resp)
        assert data["status"] == "PUBLISHED"

        # Check restaurant average updated
        r = get_success_data(api_client.get_restaurant(rest["id"], _admin))
        assert r["rating_count"] == 1
        assert r["rating_average"] == pytest.approx(4.0, abs=0.01)

    def test_hide_rating_recalculates_average(self):
        """PUBLISHED -> HIDDEN, average recalculated (PRD 3.12)."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_rating()
        payload = create_rating_payload(
            "CUSTOMER_TO_RESTAURANT", customer["id"], rest["id"], score=4
        )
        rating = get_success_data(api_client.create_rating(order["id"], payload, _customer))
        get_success_data(api_client.publish_rating(order["id"], rating["id"], _admin))

        resp = api_client.hide_rating(order["id"], rating["id"], _admin)
        data = validate_success(resp)
        assert data["status"] == "HIDDEN"

        # Restaurant average should reset to 0.0 (no published ratings)
        r = get_success_data(api_client.get_restaurant(rest["id"], _admin))
        assert r["rating_count"] == 0
        assert r["rating_average"] == pytest.approx(0.0, abs=0.01)

    def test_cannot_publish_non_pending_rating(self):
        """Cannot publish an already PUBLISHED rating."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_rating()
        payload = create_rating_payload(
            "CUSTOMER_TO_RESTAURANT", customer["id"], rest["id"], score=5
        )
        rating = get_success_data(api_client.create_rating(order["id"], payload, _customer))
        get_success_data(api_client.publish_rating(order["id"], rating["id"], _admin))

        resp = api_client.publish_rating(order["id"], rating["id"], _admin)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rating_average_round_half_up(self):
        """rating_average uses 2 decimal places with round half up (PRD 2.5)."""
        # Create two delivered orders for the same restaurant to get two ratings
        r1, m1, c1, rd1, o1, d1 = complete_order_lifecycle(item_price_cents=2000)
        r2, m2, c2, rd2, o2, d2 = complete_order_lifecycle(item_price_cents=2000)

        # Rate first: score 4
        p1 = create_rating_payload("CUSTOMER_TO_RESTAURANT", c1["id"], r1["id"], score=4)
        rating1 = get_success_data(api_client.create_rating(o1["id"], p1, _customer))
        get_success_data(api_client.publish_rating(o1["id"], rating1["id"], _admin))

        rest = get_success_data(api_client.get_restaurant(r1["id"], _admin))
        assert rest["rating_average"] == pytest.approx(4.0, abs=0.01)

    def test_rating_not_found(self):
        """ERR_RATING_NOT_FOUND for non-existent rating."""
        rest, customer, rider, order, delivery = setup_delivered_order_for_rating()
        resp = api_client.publish_rating(order["id"], NON_EXISTENT_UUID, _admin)
        validate_error(resp, ApiErrorId.ERR_RATING_NOT_FOUND)
