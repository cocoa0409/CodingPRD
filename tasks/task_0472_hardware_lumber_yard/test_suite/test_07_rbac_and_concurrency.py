"""Authentication, authorization (RBAC), and optimistic concurrency control on
sales-order place/fulfill.

Covers the Corner queue rbac section and the OCC instances of the
cross_cutting_complexity_layers section.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_vendor, create_product, create_account,
    create_order_with_line, setup_placed_order, setup_fulfilled_order,
    create_product_payload,
    api_client, SALES, INVENTORY, ACCOUNTS,
    make_contractor_headers, build_user_headers,
)


# ─── Corner: rbac ───────────────────────────────────────────────────────────

def test_contractor_cannot_create_product(api):
    """PRD 2.1: "When the headers are well-formed but the acting role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED."

    Design: Corner/rbac/contractor_cannot_create_product
    """
    vendor = create_vendor()
    account = create_account(credit_limit_cents=1000, net_terms_days=30)
    payload = create_product_payload(
        vendor["id"], sku="RB-1", sell_mode="EACH", aisle="RB", bin="QB",
        list_price_cents=100, reorder_point=0, reorder_qty=1)
    res = api.create_product(payload, make_contractor_headers(account["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


def test_sales_associate_cannot_invoice(api):
    """PRD 2.1: "When the headers are well-formed but the acting role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED."
    PRD 3.6: "only an AccountsManager drives it."

    Design: Corner/rbac/sales_associate_cannot_invoice
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    account = create_account(credit_limit_cents=1000000, net_terms_days=30)
    fulfilled = setup_fulfilled_order(product["id"], qty=5,
                                      contractor_account_id=account["id"])
    # invoice endpoint is AccountsManager-exclusive; call it as SalesAssociate.
    res = api.invoice_order(fulfilled["id"], SALES)
    validate_error(res, "ERR_UNAUTHORIZED")


def test_missing_auth_headers_returns_401(api):
    """PRD 2.1: "If either header is missing, or X-User-Role is not one of these
    five known roles, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    res = api.create_sales_order({}, headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── Corner: cross_cutting (OCC) ────────────────────────────────────────────

def test_occ_place_correct_version_succeeds(api):
    """PRD 2.7: "Both the place transition and the fulfill transition require
    the caller to supply expected_sales_order_version in the request body as a
    non-optional field carrying the version the client last observed on that
    SalesOrder."
    PRD 3.3: "On a successful placement the order's version increments by one."

    Design: Corner/cross_cutting_complexity_layers/occ_place_correct_version_succeeds
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    order, _ = create_order_with_line(product["id"], qty=5)
    current = validate_success(api.get_sales_order(order["id"], SALES), 200)
    placed = validate_success(api.place_order(
        order["id"], {"expected_sales_order_version": current["version"]}, SALES), 200)
    assert placed["fulfillment_status"] == "PLACED"
    assert placed["version"] == current["version"] + 1


def test_occ_place_stale_version_returns_412(api):
    """PRD 2.7: "If expected_sales_order_version does not equal the order's
    current version, the transition is refused with ERR_STALE_ORDER_VERSION and
    HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_place_stale_version_returns_412
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    order, _ = create_order_with_line(product["id"], qty=5)
    current = validate_success(api.get_sales_order(order["id"], SALES), 200)
    stale = current["version"] - 1
    res = api.place_order(order["id"], {"expected_sales_order_version": stale}, SALES)
    validate_error(res, "ERR_STALE_ORDER_VERSION")

    after = validate_success(api.get_sales_order(order["id"], SALES), 200)
    assert after["fulfillment_status"] == "DRAFT", "rejected place leaves order DRAFT"


def test_occ_fulfill_stale_version_returns_412(api):
    """PRD 2.7: "If expected_sales_order_version does not equal the order's
    current version, the transition is refused with ERR_STALE_ORDER_VERSION and
    HTTP status 412."
    PRD 3.3: "On a successful placement the order's version increments by one."

    Design: Corner/cross_cutting_complexity_layers/occ_fulfill_stale_version_returns_412
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    order, _ = create_order_with_line(product["id"], qty=5)
    pre_place_version = order["version"]
    placed = validate_success(api.place_order(
        order["id"], {"expected_sales_order_version": pre_place_version}, SALES), 200)
    # The place bumped version; fulfilling with the pre-place value is stale.
    res = api.fulfill_order(
        order["id"], {"expected_sales_order_version": pre_place_version}, SALES)
    validate_error(res, "ERR_STALE_ORDER_VERSION")

    after = validate_success(api.get_sales_order(order["id"], SALES), 200)
    assert after["fulfillment_status"] == "PLACED", "rejected fulfill leaves order PLACED"
