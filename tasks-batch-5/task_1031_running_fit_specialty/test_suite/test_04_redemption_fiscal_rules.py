"""Loyalty-redemption fiscal rules and the state-beats-fiscal precedence.

Queue B (Corner): calculations (redemption caps/insufficiency).
Queue A (Difficulty): priority_pair_validation_conflict.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    ApiErrorId,
    fixtures as fx,
)


# ---------------------------------------------------------------------------
# Corner: calculations — isolated fiscal checks (order UNPAID, so state passes)
# ---------------------------------------------------------------------------
def test_redemption_not_multiple_of_100_rejected(api, sm):
    """PRD 3.4: "the amount must be a whole multiple of 100 whose cent value does
    not exceed half of `subtotal_after_discount`, or the request fails with
    `ERR_REDEMPTION_EXCEEDS_CAP`."

    Design: Corner/calculations/c_redemption_not_multiple_of_100_rejected
    """
    member = fx.create_member()
    fx.grant_points(member["id"], 500)
    product = fx.create_product(category="GEAR", unit_price_cents=10000, initial_stock=3)
    order = fx.create_single_line_order(member["id"], product["id"], 1)
    resp = api.apply_redemption(order["id"], {"points_to_redeem": 150}, sm)
    validate_error(resp, ApiErrorId.ERR_REDEMPTION_EXCEEDS_CAP.value, 422)


def test_redemption_exceeds_half_subtotal_rejected(api, sm):
    """PRD 3.4: "the amount must be a whole multiple of 100 whose cent value does
    not exceed half of `subtotal_after_discount`, or the request fails with
    `ERR_REDEMPTION_EXCEEDS_CAP`."

    Design: Corner/calculations/c_redemption_exceeds_half_subtotal_rejected
    """
    member = fx.create_member()
    fx.grant_points(member["id"], 8000)
    product = fx.create_product(category="GEAR", unit_price_cents=10000, initial_stock=3)
    order = fx.create_single_line_order(member["id"], product["id"], 1)
    # 6000 cents > 50% of subtotal_after_discount 10000 (=5000).
    resp = api.apply_redemption(order["id"], {"points_to_redeem": 6000}, sm)
    validate_error(resp, ApiErrorId.ERR_REDEMPTION_EXCEEDS_CAP.value, 422)


def test_redemption_insufficient_points_rejected(api, sm):
    """PRD 3.4: "the member must hold at least `points_to_redeem` in
    `loyalty_points_balance`, or the request fails with `ERR_INSUFFICIENT_POINTS`"

    Design: Corner/calculations/c_redemption_insufficient_points_rejected
    """
    member = fx.create_member()  # 0 points
    product = fx.create_product(category="GEAR", unit_price_cents=10000, initial_stock=3)
    order = fx.create_single_line_order(member["id"], product["id"], 1)
    resp = api.apply_redemption(order["id"], {"points_to_redeem": 100}, sm)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value, 402)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / paid_order_redeem_state_beats_fiscal
# ---------------------------------------------------------------------------
def test_paid_order_redeem_state_beats_fiscal(api, sm):
    """PRD 3.4: "Redemption is only permitted while `payment_status` is `UNPAID`;
    attempting it on an order past that point yields `ERR_ORDER_NOT_MODIFIABLE`."
    PRD 2.9: "Lower-numbered checks are decisive: a request that both fails
    authentication and would fail a state check returns `ERR_UNAUTHENTICATED`,
    never the state error."

    Design: Difficulty/priority_pair_validation_conflict/paid_order_redeem_state_beats_fiscal
    """
    member = fx.create_member()  # 0 points -> fiscal would also fail
    product = fx.create_product(category="APPAREL", unit_price_cents=12000, initial_stock=3)
    order = fx.create_paid_order(member["id"], product["id"], 1)  # payment_status PAID
    # State check (priority 6) pre-empts the fiscal check (priority 10).
    resp = api.apply_redemption(order["id"], {"points_to_redeem": 100}, sm)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_MODIFIABLE.value, 409)


def test_authorized_order_redeem_state_beats_fiscal(api, sm):
    """PRD 3.4: "Redemption is only permitted while `payment_status` is `UNPAID`;
    attempting it on an order past that point yields `ERR_ORDER_NOT_MODIFIABLE`."
    PRD 2.9: "When a single request could fail more than one check, the checks
    are evaluated in a fixed priority order and the first failure determines the
    returned error."

    Design: Difficulty/priority_pair_validation_conflict/paid_order_redeem_state_beats_fiscal
    """
    member = fx.create_member()  # 0 points -> fiscal would also fail
    product = fx.create_product(category="APPAREL", unit_price_cents=12000, initial_stock=3)
    order = fx.create_single_line_order(member["id"], product["id"], 1)
    get_success_data(api.authorize_payment(order["id"], sm))  # AUTHORIZED, not UNPAID
    resp = api.apply_redemption(order["id"], {"points_to_redeem": 100}, sm)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_MODIFIABLE.value, 409)
