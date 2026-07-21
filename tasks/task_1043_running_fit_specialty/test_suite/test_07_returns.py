"""Order returns: restocking-fee refund, the return-window temporal guard, and the
state-beats-window validation precedence."""
from test_helpers import (
    validate_error, get_success_data, ApiErrorId,
    make_member_headers, make_staff_headers,
    TEST_USERS,
    fixtures as fx,
)

SM = TEST_USERS["store_manager_headers"]


def _fulfilled_order(api, price_cents=10000):
    fx.set_clock(api, "2026-07-01T00:00:00Z")
    store = fx.new_store(api)
    staff = fx.new_staff(api, store["id"], role_type="BOTH")
    member = fx.new_member(api)
    product = fx.new_product(api, category="GEAR", price_cents=price_cents, stock_on_hand=5)
    order = fx.new_fulfilled_order(api, member["id"], product["id"], staff["id"], qty=1)
    return member, product, order


def test_return_refund_nets_restocking_fee(api):
    """PRD §3.7: "A restocking fee of 15% of `final_total_cents` (rounded half-up to
    whole cents) is withheld, and the remainder — `final_total_cents` minus that
    rounded restocking fee — is recorded as the order's `refund_cents` and credited
    to the member's `wallet_credit_cents`. For each line the returned units are
    restocked: the product's `stock_on_hand` is increased by the line `qty`."

    Design: Corner/calculations/order_return_refund_nets_restocking_fee
    """
    member, product, order = _fulfilled_order(api, price_cents=10000)
    returned = get_success_data(api.return_order(order["id"], {"reason": "fit"}, make_member_headers(member["id"])))
    assert returned["status"] == "RETURNED"
    assert returned["refund_cents"] == 8500
    assert fx.get_member(api, member["id"])["wallet_credit_cents"] == 8500
    assert fx.get_product(api, product["id"])["stock_on_hand"] == 5


def test_return_after_window_expired_rejected(api):
    """PRD §3.7: "A return requested after that window has closed is rejected with
    `ERR_RETURN_WINDOW_EXPIRED` (422), and returning an order that is not `FULFILLED`
    yields `ERR_INVALID_STATE` (409)."

    Design: Corner/validations/return_after_window_on_fulfilled_order_returns_window_expired
    """
    member, product, order = _fulfilled_order(api, price_cents=2000)
    fx.set_clock(api, "2026-09-01T00:00:00Z")  # > fulfilled_at + 30 days
    resp = api.return_order(order["id"], {"reason": "late"}, make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_EXPIRED, 422)


def test_return_already_returned_reports_invalid_state_over_window(api):
    """PRD §2.8: "When several conditions could reject a request, they are evaluated
    in a fixed priority order so that the returned error is deterministic."
    PRD §2.8: "Only after all four of these pass are state, cross-entity, temporal,
    safety, and capacity rules evaluated"

    Design: Difficulty/priority_pair_validation_conflict/return_state_beats_return_window_temporal
    """
    member, product, order = _fulfilled_order(api, price_cents=500)
    get_success_data(api.return_order(order["id"], {"reason": "size"}, make_member_headers(member["id"])))
    fx.set_clock(api, "2026-09-01T00:00:00Z")  # now also past the return window
    resp = api.return_order(order["id"], {"reason": "again"}, make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_return_already_returned_leaves_order_returned(api):
    """PRD §3.7: "returning an order that is not `FULFILLED` yields
    `ERR_INVALID_STATE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/return_state_beats_return_window_temporal
    """
    member, product, order = _fulfilled_order(api, price_cents=500)
    get_success_data(api.return_order(order["id"], {"reason": "size"}, make_member_headers(member["id"])))
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    api.return_order(order["id"], {"reason": "again"}, make_member_headers(member["id"]))
    assert fx.get_order(api, order["id"])["status"] == "RETURNED"
