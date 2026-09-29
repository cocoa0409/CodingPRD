"""The two orthogonal order status dimensions and their gate (PRD §3.3, §3.11)."""

from test_helpers import (
    YEAST_INSTANT,
    ApiErrorId,
    add_order_line,
    api_client,
    create_customer,
    create_product,
    create_zone,
    open_order,
    read_order,
    read_order_line,
    receive_lot,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PC, WO, buyer_headers


def _unpriced_yeast_order():
    set_clock("2026-08-05T00:00:00Z")
    customer = create_customer()
    product = create_product(YEAST_INSTANT)
    zone = create_zone(allergen_class="NONE")
    lot = receive_lot(product["id"], zone["id"], quantity_received_lb=20000)
    order = open_order(customer, requested_delivery_on="2026-09-15T00:00:00Z")
    line = add_order_line(customer, order["id"], product["id"], 1500)
    return {
        "customer": customer,
        "product": product,
        "lot": lot,
        "order": order,
        "order_line": line,
    }


def test_submit_moves_pricing_only_and_allocate_moves_fulfillment_only():
    """PRD §3.3: "Neither dimension is derived from the other; each has its own
    transitions, and the points at which one gates the other are named explicitly
    below and in §3.9."

    Submission takes `pricing_status` to `PROVISIONAL` while `fulfillment_status`
    is still `NEW`, and allocation then takes `fulfillment_status` to `ALLOCATED`
    while `pricing_status` stays `PROVISIONAL`.

    Design: Difficulty/non_linear_state_machine/parallel_dimensions_order_pricing_and_fulfillment_advance_independently
    """
    scenario = _unpriced_yeast_order()

    submitted = validate_success(
        api_client.submit_order(scenario["order"]["id"], {}, buyer_headers(scenario["customer"]))
    )
    assert submitted["pricing_status"] == "PROVISIONAL", (
        f"Expected PROVISIONAL, got {submitted['pricing_status']}"
    )
    assert submitted["fulfillment_status"] == "NEW", (
        f"Expected the physical dimension untouched at NEW, got {submitted['fulfillment_status']}"
    )
    assert submitted["total_cents"] == 476625, (
        f"Expected total 476625, got {submitted['total_cents']}"
    )

    allocated = validate_success(api_client.allocate_order(scenario["order"]["id"], {}, WO))
    assert allocated["fulfillment_status"] == "ALLOCATED", (
        f"Expected ALLOCATED, got {allocated['fulfillment_status']}"
    )
    assert allocated["pricing_status"] == "PROVISIONAL", (
        f"Expected the commercial dimension untouched, got {allocated['pricing_status']}"
    )
    line = read_order_line(scenario["order_line"]["id"])
    assert line["lot_id"] == scenario["lot"]["id"], (
        f"Expected the line picked from {scenario['lot']['id']}, got {line['lot_id']}"
    )


def test_finalize_pricing_blocked_while_the_load_has_not_physically_closed():
    """PRD §3.11: "It requires the order to be `PROVISIONAL` on the commercial
    dimension and to have physically closed — `fulfillment_status` of `DELIVERED`
    or `SHORT_SHIPPED` — and finalizing before the load has moved is rejected
    with `ERR_ORDER_DIMENSION_GATE`."

    Design: Difficulty/non_linear_state_machine/parallel_dimensions_order_pricing_and_fulfillment_advance_independently
    """
    scenario = _unpriced_yeast_order()
    validate_success(
        api_client.submit_order(scenario["order"]["id"], {}, buyer_headers(scenario["customer"]))
    )

    response = api_client.finalize_order_pricing(scenario["order"]["id"], {}, PC)

    validate_error(response, ApiErrorId.ERR_ORDER_DIMENSION_GATE)
    order = read_order(scenario["order"]["id"])
    assert order["pricing_status"] == "PROVISIONAL", (
        f"Expected the order to stay PROVISIONAL, got {order['pricing_status']}"
    )
    assert order["fulfillment_status"] == "NEW"


def test_allocation_refused_while_nobody_has_priced_the_order():
    """PRD §3.5: "Its `pricing_status` must be either `PROVISIONAL` or `FINAL` —
    this is the cross-dimension gate, and an attempt to reserve inventory for an
    `UNPRICED` order is rejected with `ERR_ORDER_DIMENSION_GATE` (HTTP 409),
    because the warehouse does not pick against a load nobody has priced."

    Design: Difficulty/non_linear_state_machine/parallel_dimensions_order_pricing_and_fulfillment_advance_independently
    """
    scenario = _unpriced_yeast_order()

    response = api_client.allocate_order(scenario["order"]["id"], {}, WO)

    validate_error(response, ApiErrorId.ERR_ORDER_DIMENSION_GATE)
    order = read_order(scenario["order"]["id"])
    assert order["fulfillment_status"] == "NEW", (
        f"Expected NEW after the refused allocation, got {order['fulfillment_status']}"
    )
    assert read_order_line(scenario["order_line"]["id"])["allocation_status"] == "UNALLOCATED"
