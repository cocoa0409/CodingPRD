"""Special orders: immediate deposit-credit on cancel, and lifecycle state guards."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

SM = TEST_USERS["store_manager_headers"]


def test_cancel_ordered_special_order_credits_deposit_immediately(api):
    """PRD §3.7: "On cancellation, if `deposit_cents` is greater than zero, the deposit is
    refunded as store credit by minting an `ADJUST` loyalty ledger entry whose points
    equal the deposit in cents divided by 100, rounded down to a whole number, after which
    the customer's `loyalty_points_balance` recomputes."

    Design: Corner/consistency_model/special_order_cancel_deposit_credit_visible_immediately
    """
    ctx = fx.setup_placed_special_order(deposit=3000, with_stock=False)
    cancelled = validate_success(api.cancel_special_order(ctx["special_order"]["id"], SM))
    assert cancelled["status"] == "CANCELLED"
    customer = get_success_data(api.get_customer(ctx["customer"]["id"], SM))
    assert customer["loyalty_points_balance"] == 30, "floor(3000 / 100)"


def test_receive_draft_special_order_returns_invalid_state(api):
    """PRD §3.7: "Receiving the order advances `ORDERED` to `RECEIVED`... an action from
    an incompatible state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/special_order_receive_from_draft_returns_invalid_state
    """
    fx.set_clock()
    prod = fx.create_product(name="SO Shoe", brand="X", category="REGULAR", base_price_cents=7000)
    cust = fx.create_customer(full_name="SO Cust", date_of_birth="1981-01-01")
    so = get_success_data(api.create_special_order(
        {"customer_id": cust["id"], "product_id": prod["id"], "requested_size": 10.0,
         "requested_width": "D", "deposit_cents": 2000}, SM))
    resp = api.receive_special_order(so["id"], {"lot_number": "X1", "quantity_on_hand": 1}, SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
