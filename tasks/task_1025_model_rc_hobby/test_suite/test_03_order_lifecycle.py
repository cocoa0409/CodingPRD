"""Parallel order dimensions, state-vs-fiscal priority, and single-validation
order errors (hazmat, stock, payment, action, terminal lockdown)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    order_line,
    make_customer, make_product, make_order, place_order, pay_order, fulfill_order,
    make_placed_order,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


# ---------------------------------------------------------------------------
# nl_order_parallel_payment_and_fulfillment
# ---------------------------------------------------------------------------
def test_pay_settles_money_dimension_leaving_fulfillment_pending(api):
    """PRD 2.5: "The payment and fulfilment dimensions evolve independently: the
    same `PLACED` order may be paid first and fulfilled later, or fulfilled
    first and paid later, and neither transition presupposes the other except
    where a precondition explicitly requires it."

    Design: Difficulty/non_linear_state_machine/nl_order_parallel_payment_and_fulfillment
    """
    order, _buyer, _prod = make_placed_order(api, price_cents=10000,
                                             stock_on_hand=5, unit_price_cents=10000)
    paid = pay_order(api, order["id"], order["total_cents"])
    assert paid["payment_status"] == "PAID"
    assert paid["fulfillment_status"] == "PENDING"


def test_fulfill_after_pay_advances_only_fulfillment_dimension(api):
    """PRD 3.4: "Fulfilment requires that the order is `PLACED`, that its
    `payment_status` is `PAID` (else `ERR_INVALID_STATE`), and that its
    `fulfillment_status` is `PENDING`."

    Design: Difficulty/non_linear_state_machine/nl_order_parallel_payment_and_fulfillment
    """
    order, _buyer, _prod = make_placed_order(api, price_cents=10000,
                                             stock_on_hand=5, unit_price_cents=10000)
    pay_order(api, order["id"], order["total_cents"])
    fulfilled = fulfill_order(api, order["id"])
    assert fulfilled["fulfillment_status"] == "FULFILLED"
    assert fulfilled["payment_status"] == "PAID"


# ---------------------------------------------------------------------------
# pc_state_beats_fiscal_on_pay_draft_order
# ---------------------------------------------------------------------------
def test_pay_draft_order_state_error_beats_fiscal(api):
    """PRD 3.4: "Payment supplies an `amount_cents` and requires that the order
    is `PLACED`, that its `payment_status` is currently `UNPAID`, and that
    `amount_cents` is at least the order's `total_cents`".
    PRD 2.9: "State validity of the target for the requested transition is
    fourth, yielding `ERR_INVALID_STATE` (HTTP 409) whenever a resource is not
    in a state from which the transition is legal, including cross-entity state
    gates."
    PRD 2.9: "Payment sufficiency is twelfth (`ERR_INSUFFICIENT_PAYMENT`, HTTP
    402)."

    Design: Difficulty/priority_pair_validation_conflict/pc_state_beats_fiscal_on_pay_draft_order
    """
    buyer = make_customer(api)
    prod = make_product(api, product_type="KIT", price_cents=10000, stock_on_hand=5)
    order = make_order(api, buyer["id"], [order_line(prod["id"], 1, 10000)])
    # DRAFT (never placed); pay with amount far below total.
    resp = api.pay_order(order["id"], {"amount_cents": 1}, STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_pay_draft_order_leaves_order_unchanged(api):
    """PRD 2.9: "State validity of the target for the requested transition is
    fourth, yielding `ERR_INVALID_STATE` (HTTP 409) whenever a resource is not
    in a state from which the transition is legal".

    Design: Difficulty/priority_pair_validation_conflict/pc_state_beats_fiscal_on_pay_draft_order
    """
    buyer = make_customer(api)
    prod = make_product(api, product_type="KIT", price_cents=10000, stock_on_hand=5)
    order = make_order(api, buyer["id"], [order_line(prod["id"], 1, 10000)])
    api.pay_order(order["id"], {"amount_cents": 1}, STAFF)
    after = get_success_data(api.get_order(order["id"], STAFF))
    assert after["status"] == "DRAFT"
    assert after["payment_status"] == "UNPAID"


# ---------------------------------------------------------------------------
# cn_order_cancel_from_cancelled_returns_409
# ---------------------------------------------------------------------------
def test_cancel_already_cancelled_order_rejected(api):
    """PRD 3.4: "Cancelling an order — by the buyer or staff for a standard
    order, or by the system through a reservation or campaign cascade — is only
    possible while `fulfillment_status` is `PENDING`; a `FULFILLED` order can
    never be cancelled."

    Design: Corner/state_machines/cn_order_cancel_from_cancelled_returns_409
    """
    order, _buyer, _prod = make_placed_order(api, price_cents=10000,
                                             stock_on_hand=5, unit_price_cents=10000)
    validate_success(api.transition_order(order["id"], {"action": "CANCEL"}, STAFF))
    resp = api.transition_order(order["id"], {"action": "CANCEL"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# cn_transition_invalid_action_returns_400
# ---------------------------------------------------------------------------
def test_order_transition_unknown_action_rejected(api):
    """PRD 2.9: "a `/transition` request whose `action` value is not a
    recognised action for that resource is rejected with `ERR_INVALID_ACTION`
    (HTTP 400)."

    Design: Corner/state_machines/cn_transition_invalid_action_returns_400
    """
    buyer = make_customer(api)
    prod = make_product(api, product_type="KIT", price_cents=10000, stock_on_hand=5)
    order = make_order(api, buyer["id"], [order_line(prod["id"], 1, 10000)])
    resp = api.transition_order(order["id"], {"action": "TELEPORT"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_ACTION.value)


# ---------------------------------------------------------------------------
# cn_place_hazmat_without_ack_returns_409
# ---------------------------------------------------------------------------
def test_place_hazmat_order_without_ack_rejected(api):
    """PRD 2.7: "an order that contains any line whose product is a battery may
    only be placed if the buyer's `hazmat_safety_ack` is already true; otherwise
    placement is rejected with `ERR_HAZMAT_ACK_REQUIRED` (HTTP 409)."

    Design: Corner/validations/cn_place_hazmat_without_ack_returns_409
    """
    buyer = make_customer(api, ack=False)
    bat = make_product(api, product_type="BATTERY", price_cents=4000, stock_on_hand=5)
    order = make_order(api, buyer["id"], [order_line(bat["id"], 1, 4000)])
    resp = api.transition_order(order["id"], {"action": "PLACE"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_HAZMAT_ACK_REQUIRED.value)


# ---------------------------------------------------------------------------
# cn_place_order_insufficient_stock_returns_409
# ---------------------------------------------------------------------------
def test_place_order_exceeding_stock_rejected(api):
    """PRD 3.4: "Placement is refused unless the order is still `DRAFT`, unless
    every line's product has stock to cover its quantity (else
    `ERR_INSUFFICIENT_STOCK`)".

    Design: Corner/validations/cn_place_order_insufficient_stock_returns_409
    """
    buyer = make_customer(api)
    prod = make_product(api, product_type="PART", price_cents=1000, stock_on_hand=1)
    order = make_order(api, buyer["id"], [order_line(prod["id"], 5, 1000)])
    resp = api.transition_order(order["id"], {"action": "PLACE"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)


# ---------------------------------------------------------------------------
# cn_pay_insufficient_returns_402
# ---------------------------------------------------------------------------
def test_pay_below_total_rejected(api):
    """PRD 3.4: "Payment supplies an `amount_cents` and requires that the order
    is `PLACED`, that its `payment_status` is currently `UNPAID`, and that
    `amount_cents` is at least the order's `total_cents` (else
    `ERR_INSUFFICIENT_PAYMENT`, HTTP 402)."

    Design: Corner/validations/cn_pay_insufficient_returns_402
    """
    order, _buyer, _prod = make_placed_order(api, price_cents=10000,
                                             stock_on_hand=5, unit_price_cents=10000)
    assert order["total_cents"] == 10000
    resp = api.pay_order(order["id"], {"amount_cents": 5000}, STAFF)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PAYMENT.value)


# ---------------------------------------------------------------------------
# cn_pay_already_settled_returns_409
# ---------------------------------------------------------------------------
def test_pay_already_paid_order_rejected(api):
    """PRD 3.4: "Paying an order whose `payment_status` is not `UNPAID` —
    already paid or refunded — is rejected with `ERR_PAYMENT_ALREADY_SETTLED`
    (HTTP 409)."

    Design: Corner/validations/cn_pay_already_settled_returns_409
    """
    order, _buyer, _prod = make_placed_order(api, price_cents=10000,
                                             stock_on_hand=5, unit_price_cents=10000)
    pay_order(api, order["id"], order["total_cents"])
    resp = api.pay_order(order["id"], {"amount_cents": order["total_cents"]}, STAFF)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_ALREADY_SETTLED.value)
