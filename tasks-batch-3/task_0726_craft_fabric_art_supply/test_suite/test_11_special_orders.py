"""Special order state guards."""
from test_helpers import (
    validate_error, ApiErrorId,
    create_customer, create_product, create_special_order, make_customer_headers,
)


def test_confirm_special_order_from_requested_invalid_state(api):
    """PRD §3.8: "The customer confirms a quoted special order, which requires it
    be in QUOTED status (otherwise ERR_INVALID_STATE) and moves it from QUOTED to
    CONFIRMED."

    Design: Corner/state_machines/confirm_special_order_from_requested_invalid_state
    """
    customer = create_customer()
    product = create_product(sell_mode="UNIT", unit_price_cents=5000, special_order_only=True)
    special = create_special_order(customer["id"], product["id"], quantity=2)
    resp = api.confirm_special_order(special["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
