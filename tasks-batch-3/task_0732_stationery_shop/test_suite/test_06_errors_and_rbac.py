"""Error surface (NOT_FOUND, DEPOSIT_NOT_PAID) and RBAC (peer_roles, ownership)."""
import pytest
from test_helpers import (
    validate_error, get_success_data,
    api_client, TEST_USERS, NON_EXISTENT_UUID,
    create_customer, create_designer, create_paper_stock, create_finish_option,
    create_event_package, create_design_for, create_cart_order_for,
    setup_cart_order_with_line, setup_deposit_pending,
    setup_deposit_pending_with_submitted_proof,
    make_customer_headers, make_designer_headers,
    create_paper_stock_payload,
)


def test_confirm_unknown_order_returns_not_found(api):
    """PRD §2.5: "When any identifier in the path does not correspond to an existing resource,
    the server rejects the request with the corresponding 404 error before evaluating deeper
    checks: ERR_CUSTOMER_NOT_FOUND, ERR_DESIGNER_NOT_FOUND, ERR_DESIGN_NOT_FOUND,
    ERR_PROOF_NOT_FOUND, ERR_ORDER_NOT_FOUND, ERR_LINE_ITEM_NOT_FOUND,
    ERR_ADDRESSING_JOB_NOT_FOUND, ERR_WORK_ORDER_NOT_FOUND, ERR_SHIPMENT_NOT_FOUND,
    ERR_PAPER_STOCK_NOT_FOUND, ERR_FINISH_OPTION_NOT_FOUND, or ERR_EVENT_PACKAGE_NOT_FOUND."

    Design: Corner/errors/error_order_not_found_on_confirm
    """
    customer = create_customer()
    cust_headers = make_customer_headers(customer["id"])
    res = api.confirm_order(NON_EXISTENT_UUID, cust_headers)
    validate_error(res, "ERR_ORDER_NOT_FOUND")


def test_pay_deposit_wrong_amount_returns_deposit_not_paid(api):
    """PRD §3.5: "the pay-deposit or payment-simulate operation requires amount_cents to
    equal Order.deposit_due_cents exactly — partial deposits are not supported, and a
    mismatched amount is rejected with ERR_DEPOSIT_NOT_PAID."

    Design: Corner/errors/error_deposit_amount_mismatch_returns_deposit_not_paid
    """
    bundle = setup_deposit_pending(quantity=150)
    customer, order = bundle["customer"], bundle["order"]
    assert order["deposit_due_cents"] == 41250
    cust_headers = make_customer_headers(customer["id"])
    res = api.pay_deposit(order["id"], {"amount_cents": 10000}, cust_headers)
    validate_error(res, "ERR_DEPOSIT_NOT_PAID")


def test_customer_cannot_create_paper_stock(api):
    """PRD §2.1: "A request whose role is not authorised for the target endpoint — or whose
    entity-backed identity does not match the acting resource's owner — is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/customer_cannot_create_paper_stock
    """
    customer = create_customer()
    cust_headers = make_customer_headers(customer["id"])
    res = api.create_paper_stock(
        create_paper_stock_payload(name="X", base_price_cents=500, lead_days=7),
        cust_headers,
    )
    validate_error(res, "ERR_UNAUTHORIZED")


def test_customer_b_cannot_cancel_customer_a_order(api):
    """PRD §2.1: "In particular, a Customer may only act on a Design whose customer_id equals
    X-User-ID, on an Order whose customer_id equals X-User-ID, and on a Proof whose parent
    Design.customer_id equals X-User-ID."

    Design: Corner/rbac/customer_cannot_cancel_others_order
    """
    bundle = setup_cart_order_with_line()
    customer_a, order_a = bundle["customer"], bundle["order"]
    customer_b = create_customer(email="cb@x.com")
    b_headers = make_customer_headers(customer_b["id"])
    res = api.cancel_order(order_a["id"], b_headers)
    validate_error(res, "ERR_UNAUTHORIZED")


def test_designer_cannot_approve_proof(api):
    """PRD §2.1: "When X-User-Role is Customer, X-User-ID is the id of the acting Customer;
    ownership checks on any resource that references a Customer compare the resource's
    customer_id foreign key to X-User-ID. In particular, a Customer may only act on a Design
    whose customer_id equals X-User-ID, on an Order whose customer_id equals X-User-ID, and
    on a Proof whose parent Design.customer_id equals X-User-ID."

    Design: Corner/rbac/designer_cannot_approve_proof
    """
    bundle = setup_deposit_pending_with_submitted_proof()
    designer = bundle["designer"]
    des_headers = make_designer_headers(designer["id"])
    res = api.approve_proof(bundle["proof"]["id"], des_headers)
    validate_error(res, "ERR_UNAUTHORIZED")
