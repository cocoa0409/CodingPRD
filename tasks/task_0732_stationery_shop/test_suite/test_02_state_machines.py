"""State machine transitions: initial state, invalid transitions, terminal lockdown, ownership."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_customer, create_designer, create_paper_stock, create_finish_option,
    create_event_package, create_design_for, create_cart_order_for,
    setup_cart_order_with_line, setup_deposit_pending,
    setup_deposit_pending_with_submitted_proof,
    make_customer_headers, make_designer_headers,
    create_initial_proof_payload,
    api_client, TEST_USERS,
)


def test_new_order_starts_in_cart(api):
    """PRD §3.2: "A new Order starts with status CART, subtotal_cents of zero,
    total_cents of zero, rush_requested false, deposit_paid_cents and
    reorder_discount_cents and rush_surcharge_cents all zero, and
    Order.event_package_id snapshotted from the parent design."

    Design: Corner/state_machines/new_order_starts_in_cart
    """
    customer = create_customer()
    paper = create_paper_stock()
    finish = create_finish_option()
    pkg = create_event_package()
    design = create_design_for(customer, paper, finish, pkg)
    cust_headers = make_customer_headers(customer["id"])
    res = api.create_order({"customer_id": customer["id"], "design_id": design["id"]}, cust_headers)
    order = validate_success(res, 201)
    assert order["status"] == "CART"


def test_second_cancel_on_cancelled_order_returns_already_terminal(api):
    """PRD §3.9: "From any terminal state (SHIPPED cannot be cancelled through this path,
    DELIVERED and CANCELLED are terminal), a cancellation request returns ERR_ALREADY_TERMINAL."

    Design: Corner/state_machines/cancel_order_from_already_cancelled_returns_already_terminal
    """
    bundle = setup_cart_order_with_line()
    customer, order = bundle["customer"], bundle["order"]
    cust_headers = make_customer_headers(customer["id"])
    # First cancel
    get_success_data(api.cancel_order(order["id"], cust_headers))
    # Second cancel
    res = api.cancel_order(order["id"], cust_headers)
    validate_error(res, "ERR_ALREADY_TERMINAL")


def test_request_changes_on_draft_proof_returns_invalid_state(api):
    """PRD §3.6: "The customer, in turn, may request changes — transitioning
    SUBMITTED -> CHANGES_REQUESTED, clearing Proof.submitted_at back to null — or approve —
    transitioning SUBMITTED -> APPROVED, stamping Proof.approved_at, advancing Design.status
    to APPROVED, and possibly cascading the order per §2.10."
    PRD §3.6: "Any state-transition endpoint invoked from a state where the transition is
    not permitted returns ERR_INVALID_STATE."

    Design: Corner/state_machines/proof_request_changes_from_draft_returns_invalid_state
    """
    # Setup: order confirmed, initial proof still DRAFT (not yet submitted)
    bundle = setup_deposit_pending()
    designer = create_designer()
    des_headers = make_designer_headers(designer["id"])
    proof = get_success_data(api.create_proof(
        bundle["design"]["id"],
        create_initial_proof_payload(designer["id"]),
        des_headers,
    ))
    assert proof["status"] == "DRAFT"
    # Trigger: customer tries to request changes from DRAFT
    cust_headers = make_customer_headers(bundle["customer"]["id"])
    res = api.request_changes_proof(proof["id"], cust_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_designer_cannot_submit_others_proof(api):
    """PRD §2.1: "a Designer may only submit a Proof whose designer_id equals X-User-ID,
    and creating the initial proof for a Design binds the Design's designer_id to
    X-User-ID on the spot."

    Design: Corner/state_machines/designer_cannot_submit_others_proof
    """
    bundle = setup_deposit_pending()
    designer_a = create_designer(full_name="Alice")
    designer_b = create_designer(full_name="Bob")
    # Designer A creates the proof
    a_headers = make_designer_headers(designer_a["id"])
    proof = get_success_data(api.create_proof(
        bundle["design"]["id"],
        create_initial_proof_payload(designer_a["id"]),
        a_headers,
    ))
    # Designer B tries to submit it
    b_headers = make_designer_headers(designer_b["id"])
    res = api.submit_proof(proof["id"], b_headers)
    validate_error(res, "ERR_UNAUTHORIZED")
