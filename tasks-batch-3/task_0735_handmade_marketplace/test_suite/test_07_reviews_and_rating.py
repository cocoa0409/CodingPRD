"""Review eligibility, the dual simple/Bayesian shop rating, and rating recomputation on hide."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_seller_headers, make_buyer_headers,
    setup_two_reviewed_orders, setup_shop_with_completed_orders,
    setup_paid_ready_to_ship_order, create_review, get_shop,
)

BUYER = make_buyer_headers("buyer_1")


# ==========================================================================
# Difficulty / dual_variant_calc / shop_rating_simple_vs_bayesian
# ==========================================================================
def test_simple_average_rating_two_five_star_reviews(api):
    """PRD §3.7: "the `simple_avg_rating` is the plain arithmetic mean — `s` divided by
    `n`, rounded half up to two decimal places".

    Design: Difficulty/dual_variant_calc/shop_rating_simple_vs_bayesian
    """
    shop, listing, orders, reviews = setup_two_reviewed_orders(ratings=(5, 5))
    data = get_shop(shop["id"])
    assert data["published_review_count"] == 2
    assert data["simple_avg_rating"] == pytest.approx(5.0, abs=0.001)


def test_weighted_bayesian_rating_two_five_star_reviews(api):
    """PRD §3.7: "the `weighted_shop_rating` is a Bayesian-damped mean that folds in a
    prior of 5 pseudo-reviews sitting at a prior mean of 4.0 stars: it is the sum of `s`
    and the product of 5 and 4.0, divided by the sum of `n` and 5, rounded half up to two
    decimal places."

    Design: Difficulty/dual_variant_calc/shop_rating_simple_vs_bayesian
    """
    shop, listing, orders, reviews = setup_two_reviewed_orders(ratings=(5, 5))
    data = get_shop(shop["id"])
    # (10 + 5*4.0) / (2 + 5) = 30/7 = 4.2857... -> 4.29
    assert data["weighted_shop_rating"] == pytest.approx(4.29, abs=0.001)


# ==========================================================================
# Corner / validations / invalid_rating_returns_error
# ==========================================================================
def test_review_rating_out_of_range_rejected(api):
    """PRD §3.7: "The `rating` must be an integer from 1 through 5 inclusive; a rating
    outside that range or not an integer is rejected with `ERR_INVALID_RATING`
    (HTTP 400)."

    Design: Corner/validations/invalid_rating_returns_error
    """
    shop, listing, orders = setup_shop_with_completed_orders(num_orders=1, price_cents=2000,
                                                             base_cost_cents=0,
                                                             per_item_cost_cents=0,
                                                             free_shipping_threshold_cents=0)
    resp = api.create_review({"order_id": orders[0]["id"], "rating": 6}, BUYER)
    validate_error(resp, ApiErrorId.ERR_INVALID_RATING)


# ==========================================================================
# Corner / validations / duplicate_review_returns_error
# ==========================================================================
def test_second_review_on_same_order_rejected(api):
    """PRD §3.7: "At most one review may exist per order; a second attempt is rejected
    with `ERR_DUPLICATE_REVIEW` (HTTP 409)."

    Design: Corner/validations/duplicate_review_returns_error
    """
    shop, listing, orders = setup_shop_with_completed_orders(num_orders=1, price_cents=2000,
                                                             base_cost_cents=0,
                                                             per_item_cost_cents=0,
                                                             free_shipping_threshold_cents=0)
    create_review(orders[0]["id"], 5, "buyer_1")
    resp = api.create_review({"order_id": orders[0]["id"], "rating": 4}, BUYER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REVIEW)


# ==========================================================================
# Corner / validations / review_before_completed_returns_error
# ==========================================================================
def test_review_on_non_completed_order_rejected(api):
    """PRD §3.7: "The target order must be `COMPLETED` and must belong to the acting
    buyer, else `ERR_REVIEW_NOT_ALLOWED` (HTTP 422)."

    Design: Corner/validations/review_before_completed_returns_error
    """
    shop, listing, order = setup_paid_ready_to_ship_order()
    resp = api.create_review({"order_id": order["id"], "rating": 5}, BUYER)
    validate_error(resp, ApiErrorId.ERR_REVIEW_NOT_ALLOWED)


# ==========================================================================
# Corner / cross_cutting_complexity_layers / hide_review_recomputes_shop_rating
# ==========================================================================
def test_hiding_review_recomputes_shop_rating(api):
    """PRD §3.7: "Whenever a review is published or hidden, the shop's rating is
    recomputed from its currently `PUBLISHED` reviews."
    PRD §3.7: "the `simple_avg_rating` is the plain arithmetic mean — `s` divided by `n`,
    rounded half up to two decimal places".

    Design: Corner/cross_cutting_complexity_layers/hide_review_recomputes_shop_rating
    """
    shop, listing, orders, reviews = setup_two_reviewed_orders(ratings=(5, 3))
    three_star = reviews[1]
    validate_success(api.hide_review(three_star["id"], make_seller_headers(shop["id"])))
    data = get_shop(shop["id"])
    assert data["published_review_count"] == 1
    assert data["simple_avg_rating"] == pytest.approx(5.0, abs=0.001)
