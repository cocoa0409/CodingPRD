"""Placement precedence and cross-entity gates: state-before-business-rule
precedence, the ordered business checks (practitioner auth before points),
the customer-active and recommendation gates, fulfil-state validation, and
order ownership.
"""
from test_helpers import (
    validate_success, validate_error, TEST_USERS, make_customer_headers,
    new_customer, new_product, new_lot, new_practitioner, new_recommendation,
    new_order, add_line, place,
)

OPERATOR = TEST_USERS["store_operator_headers"]


def _placed_full_lot(email):
    """Customer + product + 3-unit lot + order qty 3 already PLACED (lot fully
    reserved, 0 available)."""
    cust = new_customer(email=email, full_name="Cust")
    prod = new_product(unit_price_cents=4000)
    new_lot(prod["id"], quantity_received=3, lot_number="CF-1")
    order = new_order(cust["id"])
    add_line(order["id"], cust["id"], prod["id"], 3)
    place(order["id"], cust["id"])
    return cust, order


def test_replace_placed_order_returns_invalid_state(api):
    """PRD §2.10: "the target resource being in a state that admits the requested
    transition (`ERR_INVALID_STATE`). Only after these succeed are the
    endpoint-specific business rules evaluated".

    Design: Difficulty/priority_pair_validation_conflict/state_over_inventory_conflict
    """
    cust, order = _placed_full_lot("c7@x.com")
    res = api.place_order(order["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_state_check_precedes_inventory_check_on_replace(api):
    """PRD §2.10: "the target resource being in a state that admits the requested
    transition (`ERR_INVALID_STATE`). Only after these succeed are the
    endpoint-specific business rules evaluated".

    Design: Difficulty/priority_pair_validation_conflict/state_over_inventory_conflict
    """
    cust, order = _placed_full_lot("c7b@x.com")
    res = api.place_order(order["id"], make_customer_headers(cust["id"]))
    body = res.json()
    error_id = body["data"]["error_id"]
    assert error_id == "ERR_INVALID_STATE", f"state must win, got {error_id}"
    assert error_id != "ERR_INSUFFICIENT_INVENTORY", "inventory check must not pre-empt state"


def _practitioner_line_order_overspending_points(email):
    """Customer (0 points) + practitioner-line product + lot + order redeeming
    100 points with one line, no recommendation issued."""
    cust = new_customer(email=email, full_name="Cust")
    prod = new_product(unit_price_cents=5000, is_practitioner_line=True, regimen_goals=["JOINT"])
    new_lot(prod["id"], quantity_received=10, lot_number="RX-1")
    order = new_order(cust["id"], points_redeemed=100)
    add_line(order["id"], cust["id"], prod["id"], 1)
    return cust, order


def test_practitioner_auth_reported_over_insufficient_points(api):
    """PRD §3.6: "First, for every line whose product is a practitioner line,
    there must exist an `ISSUED`, non-expired `Recommendation` for that customer
    and product whose already-consumed units plus this line's quantity do not
    exceed its `max_units`; a line lacking such backing is rejected with
    `ERR_PRACTITIONER_AUTH_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_over_fiscal_conflict
    """
    cust, order = _practitioner_line_order_overspending_points("c8@x.com")
    res = api.place_order(order["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_PRACTITIONER_AUTH_REQUIRED", expected_status=403)


def test_practitioner_auth_precedes_points_affordability(api):
    """PRD §3.6: "Finally, the redemption must be affordable: `points_redeemed`
    must not exceed the customer's `points_balance` and the redemption value must
    not exceed the order's provisional subtotal, or the placement is rejected
    with `ERR_INSUFFICIENT_POINTS`."

    Design: Difficulty/priority_pair_validation_conflict/safety_over_fiscal_conflict
    """
    cust, order = _practitioner_line_order_overspending_points("c8b@x.com")
    res = api.place_order(order["id"], make_customer_headers(cust["id"]))
    error_id = res.json()["data"]["error_id"]
    assert error_id == "ERR_PRACTITIONER_AUTH_REQUIRED", f"got {error_id}"
    assert error_id != "ERR_INSUFFICIENT_POINTS", "points check must not pre-empt practitioner auth"


def test_place_suspended_customer_rejected(api):
    """PRD §3.6: "The buyer must be `ACTIVE`, or the placement is rejected with
    `ERR_CUSTOMER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/order_place_requires_customer_active
    """
    cust = new_customer(email="c11@x.com", full_name="Cust Eleven")
    prod = new_product(unit_price_cents=1000)
    new_lot(prod["id"], quantity_received=10, lot_number="SU-1")
    order = new_order(cust["id"])
    add_line(order["id"], cust["id"], prod["id"], 1)
    validate_success(api.suspend_customer(cust["id"], OPERATOR), 200)
    res = api.place_order(order["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_CUSTOMER_SUSPENDED", expected_status=409)


def test_place_active_customer_succeeds(api):
    """PRD §3.6: "The buyer must be `ACTIVE`, or the placement is rejected with
    `ERR_CUSTOMER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/order_place_requires_customer_active
    """
    cust = new_customer(email="c11b@x.com", full_name="Cust Eleven B")
    prod = new_product(unit_price_cents=1000)
    new_lot(prod["id"], quantity_received=10, lot_number="SU-2")
    order = new_order(cust["id"])
    add_line(order["id"], cust["id"], prod["id"], 1)
    placed = place(order["id"], cust["id"])
    assert placed["status"] == "PLACED"


def test_place_practitioner_line_with_valid_recommendation_succeeds(api):
    """PRD §3.4: "A new recommendation begins with `status` `ISSUED` and
    `consumed_units` of 0."
    PRD §3.6: "there must exist an `ISSUED`, non-expired `Recommendation` for that
    customer and product whose already-consumed units plus this line's quantity
    do not exceed its `max_units`; a line lacking such backing is rejected with
    `ERR_PRACTITIONER_AUTH_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/practitioner_line_requires_recommendation
    """
    cust = new_customer(email="c12@x.com", full_name="Cust Twelve")
    prac = new_practitioner(full_name="Dr Ada", license_number="LIC-1")
    prod = new_product(unit_price_cents=5000, is_practitioner_line=True)
    new_lot(prod["id"], quantity_received=10, lot_number="RXOK-1")
    new_recommendation(prac["id"], cust["id"], prod["id"],
                       expires_at="2026-12-31T00:00:00Z", max_units=5)
    order = new_order(cust["id"])
    add_line(order["id"], cust["id"], prod["id"], 2)
    placed = place(order["id"], cust["id"])
    assert placed["status"] == "PLACED"


def test_place_practitioner_line_without_recommendation_rejected(api):
    """PRD §3.6: "there must exist an `ISSUED`, non-expired `Recommendation` for
    that customer and product whose already-consumed units plus this line's
    quantity do not exceed its `max_units`; a line lacking such backing is
    rejected with `ERR_PRACTITIONER_AUTH_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/practitioner_line_requires_recommendation
    """
    cust = new_customer(email="c12b@x.com", full_name="Cust Twelve B")
    prod = new_product(unit_price_cents=5000, is_practitioner_line=True)
    new_lot(prod["id"], quantity_received=10, lot_number="RXNO-1")
    order = new_order(cust["id"])
    add_line(order["id"], cust["id"], prod["id"], 2)
    res = api.place_order(order["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_PRACTITIONER_AUTH_REQUIRED", expected_status=403)


def test_fulfill_draft_order_rejected(api):
    """PRD §2.10: "the target resource being in a state that admits the requested
    transition (`ERR_INVALID_STATE`)."
    PRD §3.6: "Fulfilling a placed order is a `StoreOperator` action, advancing it
    from `PLACED` to `FULFILLED`."

    Design: Corner/state_machines/corner_fulfill_draft_order_invalid_state
    """
    cust = new_customer(email="sm2@x.com", full_name="SM Two")
    prod = new_product(unit_price_cents=1000)
    order = new_order(cust["id"])
    add_line(order["id"], cust["id"], prod["id"], 1)
    res = api.fulfill_order(order["id"], OPERATOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_customer_cannot_place_another_customers_order(api):
    """PRD §2.1: "A customer acting on a resource they do not own is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/corner_customer_cannot_place_others_order_not_owner
    """
    cust_a = new_customer(email="ra@x.com", full_name="Cust A")
    cust_b = new_customer(email="rb@x.com", full_name="Cust B")
    prod = new_product(unit_price_cents=1000)
    new_lot(prod["id"], quantity_received=10, lot_number="OW-1")
    order_a = new_order(cust_a["id"])
    add_line(order_a["id"], cust_a["id"], prod["id"], 1)
    res = api.place_order(order_a["id"], make_customer_headers(cust_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)
