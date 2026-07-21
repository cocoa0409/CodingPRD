"""Payment: store-credit sufficiency, the already-paid state precedence over the
fiscal check, and store-credit conservation across pay-then-cancel.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    ApiErrorId,
    make_customer_headers,
    new_store,
    new_customer,
    new_sku,
    create_order,
    order_line,
)


def _order_for(api, credit=0, base_price=4000, on_hand=10, qty=1):
    store = new_store(api)
    customer = new_customer(api, initial_store_credit_cents=credit)
    cust = customer["id"]
    sku = new_sku(api, store["id"], base_price_cents=base_price, initial_on_hand_qty=on_hand)
    order = create_order(api, cust, store["id"], [order_line(sku["id"], qty)])
    return cust, order


def test_pay_store_credit_insufficient_returns_payment_required(api):
    """PRD §3.5: "When the method is `STORE_CREDIT`, the buyer's
    `store_credit_balance_cents` must be at least the order's
    `total_before_credit_cents`, or the payment is rejected with
    `ERR_INSUFFICIENT_STORE_CREDIT`; on success `store_credit_applied_cents` is
    set to `total_before_credit_cents` and that amount is debited from the
    buyer's `store_credit_balance_cents`."

    Design: Corner/validations/pay_store_credit_insufficient_returns_payment_required
    """
    cust, order = _order_for(api, credit=100, base_price=4000, qty=1)
    resp = api.pay_order(order["id"], {"payment_method": "STORE_CREDIT"},
                         make_customer_headers(cust))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STORE_CREDIT.value)


def test_pay_already_paid_state_beats_insufficient_credit_fiscal_card_first(api):
    """PRD §3.5: "Payment requires a `payment_method` of either `STORE_CREDIT`
    or `CARD` and requires the order to currently be `UNPAID`; paying an order
    that is not `UNPAID` is rejected with `ERR_ORDER_ALREADY_PAID`." — this
    state check precedes the store-credit sufficiency check named later in the
    same workflow.

    Design: Difficulty/priority_pair_validation_conflict/pay_already_paid_state_beats_insufficient_credit_fiscal
    """
    cust, order = _order_for(api, credit=0, base_price=5000, qty=1)
    # First payment by CARD -> order becomes PAID.
    get_success_data(api.pay_order(order["id"], {"payment_method": "CARD"},
                                   make_customer_headers(cust)))
    # Re-pay with STORE_CREDIT: order is PAID (state) AND credit 0 < 5000 (fiscal).
    resp = api.pay_order(order["id"], {"payment_method": "STORE_CREDIT"},
                         make_customer_headers(cust))
    validate_error(resp, ApiErrorId.ERR_ORDER_ALREADY_PAID.value)


def test_pay_already_paid_state_beats_insufficient_credit_fiscal_credit_first(api):
    """PRD §3.5: "paying an order that is not `UNPAID` is rejected with
    `ERR_ORDER_ALREADY_PAID`." — even when the retried method's fiscal check
    would also fail, the already-paid state error is returned.

    Design: Difficulty/priority_pair_validation_conflict/pay_already_paid_state_beats_insufficient_credit_fiscal
    """
    cust, order = _order_for(api, credit=5000, base_price=5000, qty=1)
    # First payment by STORE_CREDIT consumes the whole balance (now 0).
    get_success_data(api.pay_order(order["id"], {"payment_method": "STORE_CREDIT"},
                                   make_customer_headers(cust)))
    # Re-pay with STORE_CREDIT: order is PAID (state) AND credit 0 < 5000 (fiscal).
    resp = api.pay_order(order["id"], {"payment_method": "STORE_CREDIT"},
                         make_customer_headers(cust))
    validate_error(resp, ApiErrorId.ERR_ORDER_ALREADY_PAID.value)


def test_pay_credit_then_cancel_conserves_store_credit_balance(api):
    """PRD §3.5: "on success `store_credit_applied_cents` is set to
    `total_before_credit_cents` and that amount is debited from the buyer's
    `store_credit_balance_cents`."
    PRD §3.4: "If the cancelled order had already been paid, cancellation also
    reverses the money: any `store_credit_applied_cents` is refunded to the
    buyer's `store_credit_balance_cents`, `payment_status` moves to `REFUNDED`,
    and the buyer's `lifetime_spend_cents` and the loyalty points this order
    accrued are both unwound."

    Design: Difficulty/compensating_invariant/pay_credit_then_cancel_conserves_store_credit_balance
    """
    store = new_store(api)
    customer = new_customer(api, initial_store_credit_cents=10000)
    cust = customer["id"]
    sku = new_sku(api, store["id"], base_price_cents=6000, initial_on_hand_qty=100)
    order = create_order(api, cust, store["id"], [order_line(sku["id"], 1)])
    get_success_data(api.pay_order(order["id"], {"payment_method": "STORE_CREDIT"},
                                   make_customer_headers(cust)))
    cancelled = get_success_data(api.cancel_order(order["id"], make_customer_headers(cust)))
    cust_data = get_success_data(api.get_customer(cust, make_customer_headers(cust)))
    assert cancelled["store_credit_applied_cents"] == 6000
    assert cancelled["payment_status"] == "REFUNDED"
    assert cust_data["store_credit_balance_cents"] == 10000


def test_pay_credit_then_cancel_conserves_balance_full_spend(api):
    """PRD §3.4: "any `store_credit_applied_cents` is refunded to the buyer's
    `store_credit_balance_cents`, `payment_status` moves to `REFUNDED`, and the
    buyer's `lifetime_spend_cents` and the loyalty points this order accrued are
    both unwound."

    Design: Difficulty/compensating_invariant/pay_credit_then_cancel_conserves_store_credit_balance
    """
    store = new_store(api)
    customer = new_customer(api, initial_store_credit_cents=5000)
    cust = customer["id"]
    sku = new_sku(api, store["id"], base_price_cents=5000, initial_on_hand_qty=100)
    order = create_order(api, cust, store["id"], [order_line(sku["id"], 1)])
    get_success_data(api.pay_order(order["id"], {"payment_method": "STORE_CREDIT"},
                                   make_customer_headers(cust)))  # balance -> 0
    get_success_data(api.cancel_order(order["id"], make_customer_headers(cust)))
    cust_data = get_success_data(api.get_customer(cust, make_customer_headers(cust)))
    assert cust_data["store_credit_balance_cents"] == 5000
    assert cust_data["lifetime_spend_cents"] == 0
