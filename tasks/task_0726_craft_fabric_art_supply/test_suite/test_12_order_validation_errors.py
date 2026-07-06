"""Order-flow validation errors and priority-ordered conflicts.

PRD §2.8 explicitly pins the validation priority order and states a lower-numbered
check always resolves before a higher-numbered one, so the priority-conflict
outcomes below are uniquely derivable from PRD prose.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_customer, create_product, create_product_with_lot, create_inventory_lot,
    create_order, create_order_with_line, add_line, submit_order, pay_order,
    make_customer_headers, create_order_line_payload,
)
from test_helpers import TEST_USERS


def test_submit_empty_order_rejected(api):
    """PRD §3.4: "Submission requires at least one order line, otherwise
    ERR_EMPTY_ORDER"

    Design: Difficulty/boundary_precision_check/submit_empty_order_zero_lines_boundary
    """
    customer = create_customer()
    order = create_order(customer["id"])
    resp = api.submit_order(order["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER)


def test_submit_single_line_order_succeeds(api):
    """PRD §3.4: "Submitting an order advances fulfillment_status from BUILDING to
    SUBMITTED. Submission requires at least one order line, otherwise
    ERR_EMPTY_ORDER"

    Design: Difficulty/boundary_precision_check/submit_empty_order_zero_lines_boundary
    """
    customer = create_customer()
    product, _ = create_product_with_lot(on_hand_yards=10, sell_mode="UNIT", unit_price_cents=100)
    order, _ = create_order_with_line(customer["id"], product["id"], requested_yards=1)
    data = validate_success(api.submit_order(order["id"], make_customer_headers(customer["id"])))
    assert data["fulfillment_status"] == "SUBMITTED"


def test_pay_building_order_redeeming_points_returns_invalid_state(api):
    """PRD §2.8: "A lower-numbered check always resolves before a higher-numbered
    one, so an earlier failure masks any later condition."
    PRD §3.5: "Payment requires that the order's fulfillment_status be SUBMITTED,
    otherwise ERR_INVALID_STATE."

    Design: Difficulty/priority_pair_validation_conflict/order_invalid_state_beats_insufficient_points_on_pay
    """
    customer = create_customer()
    order = create_order(customer["id"])  # still BUILDING, points_balance=0
    resp = api.pay_order(
        order["id"], {"points_redeemed_on_order": 100}, make_customer_headers(customer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_state_check_precedes_points_check_on_pay(api):
    """PRD §2.8: "the target resource being in the correct state for the operation
    ... and (12) sufficiency of inventory or loyalty points for the operation."
    PRD §3.5: "Payment requires that the order's fulfillment_status be SUBMITTED,
    otherwise ERR_INVALID_STATE."

    Design: Difficulty/priority_pair_validation_conflict/order_invalid_state_beats_insufficient_points_on_pay
    """
    customer = create_customer()
    order = create_order(customer["id"])
    # Redeem far more points than owned (0); state check (priority 5) must mask it.
    resp = api.pay_order(
        order["id"], {"points_redeemed_on_order": 999999}, make_customer_headers(customer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_submit_insufficient_inventory(api):
    """PRD §3.4: "for each by-the-yard line, the referenced product's lot must have
    available_yards at least the line's requested_yards, otherwise
    ERR_INSUFFICIENT_INVENTORY."

    Design: Corner/validations/submit_insufficient_inventory
    """
    customer = create_customer()
    product, _ = create_product_with_lot(
        on_hand_yards=5, sell_mode="BY_YARD", unit_price_cents=100, min_cut_increment_yards=1
    )
    order, _ = create_order_with_line(customer["id"], product["id"], requested_yards=20)
    resp = api.submit_order(order["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)


def test_ready_requires_paid_order(api):
    """PRD §3.4: "This step requires that payment_status be PAID, otherwise
    ERR_ORDER_NOT_PAID"

    Design: Corner/validations/ready_requires_paid_order
    """
    customer = create_customer()
    product, _ = create_product_with_lot(on_hand_yards=10, sell_mode="UNIT", unit_price_cents=300)
    order, _ = create_order_with_line(customer["id"], product["id"], requested_yards=1)
    submit_order(order["id"], customer["id"])
    resp = api.ready_order(order["id"], TEST_USERS["store_associate_headers"])
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_PAID)


def test_cut_not_recorded_blocks_ready(api):
    """PRD §3.4: "and that every by-the-yard line already has its actual_cut_yards
    recorded, otherwise ERR_CUT_NOT_RECORDED."

    Design: Corner/errors/cut_not_recorded_blocks_ready
    """
    customer = create_customer()
    product, _ = create_product_with_lot(
        on_hand_yards=20, sell_mode="BY_YARD", unit_price_cents=200, min_cut_increment_yards=1
    )
    order, _ = create_order_with_line(customer["id"], product["id"], requested_yards=2)
    submit_order(order["id"], customer["id"])
    pay_order(order["id"], customer["id"])
    resp = api.ready_order(order["id"], TEST_USERS["store_associate_headers"])
    validate_error(resp, ApiErrorId.ERR_CUT_NOT_RECORDED)


def test_cut_increment_violation_rejected(api):
    """PRD §3.4: "For a by-the-yard product, requested_yards must be a positive
    multiple of that product's min_cut_increment_yards; otherwise the line is
    rejected with ERR_INVALID_CUT_INCREMENT."

    Design: Corner/validations/cut_increment_violation_rejected
    """
    customer = create_customer()
    product = create_product(sell_mode="BY_YARD", unit_price_cents=400, min_cut_increment_yards=0.25)
    order = create_order(customer["id"])
    resp = api.add_order_line(
        order["id"],
        create_order_line_payload(product["id"], requested_yards=0.3),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_CUT_INCREMENT)
