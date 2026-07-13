"""Role-based access control and order-eligibility / fiscal validations.
Every test translates one corner-design instance."""
from test_helpers import (
    validate_success, validate_error,
    create_catalog_item_payload, create_customer_payload, create_order_payload,
    TEST_USERS, make_customer_headers,
    set_clock, create_catalog_item, create_inventory_unit, create_funded_customer,
)

ADMIN = TEST_USERS["admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


# ─── RBAC ─────────────────────────────────────────────────────────────

def test_warehouse_cannot_place_order_returns_403(api):
    """PRD 2.1: "When the headers are valid but the named role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/warehouse_cannot_place_order_returns_403
    """
    cat = validate_success(api.create_catalog(create_catalog_item_payload(), ADMIN), 201)
    res = api.create_order(create_order_payload(cat["id"], "RENT", rental_term_days=90), WAREHOUSE)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_customer_cannot_confirm_order_returns_403(api):
    """PRD 2.1: "When the headers are valid but the named role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/customer_cannot_confirm_order_returns_403
    """
    set_clock("2026-03-01T00:00:00Z")
    cat = create_catalog_item()
    create_inventory_unit(cat["id"], condition_grade="GOOD")
    cust = create_funded_customer(50000, email="cf@x.com")
    headers = make_customer_headers(cust["id"])
    order = validate_success(api.create_order(
        create_order_payload(cat["id"], "RENT", rental_term_days=90,
                             desired_start_date="2026-03-01T00:00:00Z"), headers), 201)
    validate_success(api.pay_order(order["id"], headers), 200)
    res = api.confirm_order(order["id"], headers)  # Customer calling WarehouseAgent-only op
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_missing_auth_headers_returns_401(api):
    """PRD 2.1: "If either header is missing, or if `X-User-Role` is not one of these
    three known roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    cat = validate_success(api.create_catalog(create_catalog_item_payload(), ADMIN), 201)
    res = api.get_catalog(cat["id"], {})  # no X-User-ID / X-User-Role
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── Item eligibility (referential business rules) ────────────────────

def test_rent_item_not_rentable_returns_422(api):
    """PRD 3.3: "a `RENT` order requires `rentable` to be true (else
    `ERR_ITEM_NOT_RENTABLE`)".

    Design: Corner/validations/rent_item_not_rentable_returns_422
    """
    cat = validate_success(api.create_catalog(
        create_catalog_item_payload(rentable=False), ADMIN), 201)
    cust = validate_success(api.create_customer(create_customer_payload(email="nr@x.com"), ADMIN), 201)
    headers = make_customer_headers(cust["id"])
    res = api.create_order(create_order_payload(cat["id"], "RENT", rental_term_days=90), headers)
    validate_error(res, "ERR_ITEM_NOT_RENTABLE", expected_status=422)


def test_buy_item_not_buyable_returns_422(api):
    """PRD 3.3: "a `BUY` order requires `buyable` to be true (else
    `ERR_ITEM_NOT_BUYABLE`)".

    Design: Corner/validations/buy_item_not_buyable_returns_422
    """
    cat = validate_success(api.create_catalog(
        create_catalog_item_payload(buyable=False), ADMIN), 201)
    cust = validate_success(api.create_customer(create_customer_payload(email="nb@x.com"), ADMIN), 201)
    headers = make_customer_headers(cust["id"])
    res = api.create_order(create_order_payload(cat["id"], "BUY"), headers)
    validate_error(res, "ERR_ITEM_NOT_BUYABLE", expected_status=422)


def test_ebook_not_available_returns_422(api):
    """PRD 3.3: "an `EBOOK` order requires `ebook_available` to be true (else
    `ERR_ITEM_NOT_EBOOK_AVAILABLE`)".

    Design: Corner/validations/ebook_not_available_returns_422
    """
    cat = validate_success(api.create_catalog(create_catalog_item_payload(), ADMIN), 201)  # ebook_available defaults false
    cust = validate_success(api.create_customer(create_customer_payload(email="ne@x.com"), ADMIN), 201)
    headers = make_customer_headers(cust["id"])
    res = api.create_order(create_order_payload(cat["id"], "EBOOK", rental_term_days=30), headers)
    validate_error(res, "ERR_ITEM_NOT_EBOOK_AVAILABLE", expected_status=422)


def test_pay_insufficient_credit_returns_402(api):
    """PRD 3.3: "the customer's `wallet_credit_cents` must be at least
    `quoted_charge_cents`; if it is not, the payment is refused with
    `ERR_INSUFFICIENT_CREDIT`."

    Design: Corner/validations/pay_insufficient_credit_returns_402
    """
    set_clock("2026-03-01T00:00:00Z")
    cat = create_catalog_item()
    cust = validate_success(api.create_customer(create_customer_payload(email="ic@x.com"), ADMIN), 201)
    headers = make_customer_headers(cust["id"])
    order = validate_success(api.create_order(
        create_order_payload(cat["id"], "RENT", rental_term_days=90,
                             desired_start_date="2026-03-01T00:00:00Z"), headers), 201)
    res = api.pay_order(order["id"], headers)  # wallet is 0
    validate_error(res, "ERR_INSUFFICIENT_CREDIT", expected_status=402)


def test_cancel_delivered_ebook_returns_422(api):
    """PRD 3.3: "An ebook order whose access has already been delivered cannot be
    cancelled or refunded, and such an attempt is rejected with
    `ERR_EBOOK_ALREADY_DELIVERED`."

    Design: Corner/validations/cancel_delivered_ebook_returns_422
    """
    set_clock("2026-03-01T00:00:00Z")
    cat = create_catalog_item(ebook_available=True)
    cust = create_funded_customer(50000, email="ed@x.com")
    headers = make_customer_headers(cust["id"])
    order = validate_success(api.create_order(
        create_order_payload(cat["id"], "EBOOK", rental_term_days=30), headers), 201)
    validate_success(api.pay_order(order["id"], headers), 200)  # delivers access
    res = api.cancel_order(order["id"], headers)
    validate_error(res, "ERR_EBOOK_ALREADY_DELIVERED", expected_status=422)


def test_ebook_license_overlap_returns_409(api):
    """PRD 3.3: "When an ebook order is placed, its access window `[access_start,
    access_end)` must not overlap the customer's existing active ebook access window for
    the same title; this half-open test adds no buffer, so an adjacency where one
    window's end equals the next window's start is allowed, and a genuine overlap is
    rejected with `ERR_EBOOK_LICENSE_OVERLAP`."

    Design: Corner/validations/ebook_license_overlap_returns_409
    """
    set_clock("2026-03-01T00:00:00Z")
    cat = create_catalog_item(ebook_available=True)
    cust = create_funded_customer(50000, email="el@x.com")
    headers = make_customer_headers(cust["id"])
    order1 = validate_success(api.create_order(
        create_order_payload(cat["id"], "EBOOK", rental_term_days=30), headers), 201)
    validate_success(api.pay_order(order1["id"], headers), 200)
    res = api.create_order(create_order_payload(cat["id"], "EBOOK", rental_term_days=30), headers)
    validate_error(res, "ERR_EBOOK_LICENSE_OVERLAP", expected_status=409)
