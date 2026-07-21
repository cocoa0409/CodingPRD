"""Order lifecycle: the two independent status axes, and invalid-transition
lockdowns on the fulfillment axis."""
import pytest

from test_helpers import (
    validate_success, validate_error, api_client,
    new_customer, new_stocked_product, new_retail_order, confirm_order, pay_order,
    ship_order, order_line, TEST_USERS, make_customer_headers,
)

ADMIN = TEST_USERS["store_admin_headers"]


# ─── Difficulty: non_linear_state_machine / independent order axes ─────────
def _setup_draft_order():
    customer = new_customer(email="par@x.com", full_name="Par Allel")
    product, _lot = new_stocked_product(quantity=50, sku_code="SYS-2", name="DWC Kit",
                                        category="SYSTEM", unit_price_cents=8000)
    order = new_retail_order(customer["id"], [order_line(product["id"], 2)])
    return customer, product, order


def test_pay_draft_then_confirm_both_axes_advance(api):
    """PRD §3.5: "An order carries two independent status axes that evolve
    separately: `fulfillment_status` and `payment_status`. A `DRAFT` order can be
    paid before it is confirmed, and a `CONFIRMED` order can still be unpaid; the
    two never gate each other except where explicitly stated."

    Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_axes_independent
    """
    customer, product, order = _setup_draft_order()
    pay_order(order["id"], customer["id"])
    confirmed = confirm_order(order["id"], customer["id"])
    assert confirmed["payment_status"] == "PAID"
    assert confirmed["fulfillment_status"] == "CONFIRMED"


def test_pay_keeps_fulfillment_draft(api):
    """PRD §3.5: "A `DRAFT` order can be paid before it is confirmed, and a
    `CONFIRMED` order can still be unpaid; the two never gate each other except
    where explicitly stated."
    PRD §3.5: "A `Customer` pays an order, moving `payment_status`
    `UNPAID → PAID`".

    Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_axes_independent
    """
    customer, product, order = _setup_draft_order()
    paid = pay_order(order["id"], customer["id"])
    assert paid["payment_status"] == "PAID"
    assert paid["fulfillment_status"] == "DRAFT"


# ─── Corner: state_machines / invalid transitions on fulfillment axis ──────
def test_confirm_already_confirmed_rejected(api):
    """PRD §3.5: "A retail `DRAFT` order is confirmed by its `Customer` (or by a
    `StoreAdmin`), moving it `DRAFT → CONFIRMED`".
    PRD §2.9: "then the state legality of the requested transition
    (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/confirm_already_confirmed_returns_invalid_state
    """
    customer = new_customer(email="ic@x.com", full_name="I C")
    product, _lot = new_stocked_product(quantity=50, sku_code="SYS-C", name="Kit C",
                                        category="SYSTEM", unit_price_cents=4000)
    order = new_retail_order(customer["id"], [order_line(product["id"], 1)])
    confirm_order(order["id"], customer["id"])
    headers = make_customer_headers(customer["id"])
    res = api.confirm_order(order["id"], headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_cancel_shipped_order_rejected(api):
    """PRD §3.5: "A `Customer` or `StoreAdmin` cancels an order that is `DRAFT` or
    `CONFIRMED`, moving it to `CANCELLED`."
    PRD §2.9: "then the state legality of the requested transition
    (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/cancel_shipped_order_returns_invalid_state
    """
    customer = new_customer(email="sh@x.com", full_name="S H")
    product, _lot = new_stocked_product(quantity=50, sku_code="SYS-D", name="Kit D",
                                        category="SYSTEM", unit_price_cents=4000)
    order = new_retail_order(customer["id"], [order_line(product["id"], 1)])
    confirm_order(order["id"], customer["id"])
    ship_order(order["id"])
    res = api.cancel_order(order["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE")
