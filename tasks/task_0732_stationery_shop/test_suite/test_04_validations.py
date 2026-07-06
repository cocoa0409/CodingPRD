"""Validation checks that surface distinct business rule errors."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, TEST_USERS, NON_EXISTENT_UUID,
    create_customer, create_designer, create_paper_stock, create_finish_option,
    create_event_package, create_design_for, create_cart_order_for,
    add_line_item_to_cart, set_clock, confirm_order, simulate_deposit_full,
    setup_delivered_order,
    make_customer_headers, make_designer_headers,
    create_line_item_payload, create_design_payload,
    setup_cart_order_with_line, setup_in_production_order,
    setup_deposit_pending_with_submitted_proof, approve_proof,
    create_initial_proof_payload,
)


def test_line_item_quantity_below_package_min_returns_below_min(api):
    """PRD §3.3: "It also requires quantity to be at least the parent order's
    event_package.min_qty — a value below the minimum is rejected with ERR_QUANTITY_BELOW_MIN."

    Design: Corner/validations/line_item_quantity_below_min_returns_below_min
    """
    customer = create_customer()
    paper = create_paper_stock()
    finish = create_finish_option()
    pkg = create_event_package(min_qty=50)
    design = create_design_for(customer, paper, finish, pkg)
    order = create_cart_order_for(customer, design)
    cust_headers = make_customer_headers(customer["id"])
    payload = create_line_item_payload(
        paper_stock_id=paper["id"], finish_option_id=finish["id"],
        quantity=10, expected_order_version=order["version"],
    )
    res = api.add_line_item(order["id"], payload, cust_headers)
    validate_error(res, "ERR_QUANTITY_BELOW_MIN")


def test_line_item_quantity_zero_returns_quantity_invalid(api):
    """PRD §3.3: "Adding a line item requires quantity to be at least one and an integer —
    a non-integer or non-positive value is rejected with ERR_QUANTITY_INVALID."

    Design: Corner/validations/line_item_quantity_zero_returns_invalid
    """
    customer = create_customer()
    paper = create_paper_stock()
    finish = create_finish_option()
    pkg = create_event_package()
    design = create_design_for(customer, paper, finish, pkg)
    order = create_cart_order_for(customer, design)
    cust_headers = make_customer_headers(customer["id"])
    payload = create_line_item_payload(
        paper_stock_id=paper["id"], finish_option_id=finish["id"],
        quantity=0, expected_order_version=order["version"],
    )
    res = api.add_line_item(order["id"], payload, cust_headers)
    validate_error(res, "ERR_QUANTITY_INVALID")


def test_reorder_prior_order_different_customer_returns_window_expired(api):
    """PRD §3.2: "when prior_order_id is provided, the referenced prior Order must belong to
    the same customer, must be in DELIVERED status, and must have been created within the
    reorder window — that is, the calendar-day difference between the new order's created_at
    and the prior order's created_at must be at most 365 days. If any of those preconditions
    is violated, the create is rejected with ERR_REORDER_WINDOW_EXPIRED."

    Design: Corner/validations/reorder_wrong_customer_returns_window_expired
    """
    set_clock("2026-04-01T00:00:00Z")
    # Customer A: DELIVERED order
    bundle_a = setup_delivered_order()
    customer_a = bundle_a["customer"]
    o_a = bundle_a["order"]
    # Customer B: new customer
    customer_b = create_customer(email="cb@x.com")
    # Reuse existing catalog from bundle_a
    paper = bundle_a["paper"]
    finish = bundle_a["finish"]
    pkg = bundle_a["package"]
    design_b = create_design_for(customer_b, paper, finish, pkg)
    b_headers = make_customer_headers(customer_b["id"])
    payload = {
        "customer_id": customer_b["id"],
        "design_id": design_b["id"],
        "prior_order_id": o_a["id"],
    }
    res = api.create_order(payload, b_headers)
    validate_error(res, "ERR_REORDER_WINDOW_EXPIRED")


def test_apply_rush_after_proof_approved_returns_rush_too_late(api):
    """PRD §3.4: "A rush request that arrives after Proof.status == APPROVED is rejected
    with ERR_RUSH_TOO_LATE — once the customer has signed off, the deadline for accepting
    a rush has passed."

    Design: Corner/validations/apply_rush_after_proof_approved_returns_rush_too_late
    """
    set_clock("2026-04-01T00:00:00Z")
    # Setup: order confirmed, proof approved (but no deposit yet — proof approval doesn't
    # require deposit to reach APPROVED; the cascade to IN_PRODUCTION does)
    bundle = setup_deposit_pending_with_submitted_proof()
    bundle["proof"] = approve_proof(bundle["customer"], bundle["proof"])
    cust_headers = make_customer_headers(bundle["customer"]["id"])
    res = api.apply_rush(bundle["order"]["id"],
                         {"rush_deadline": "2026-04-08T00:00:00Z"}, cust_headers)
    validate_error(res, "ERR_RUSH_TOO_LATE")
