"""Catalog registration, customer onboarding, wallet balance, and creation-time
input validation. Every test translates one corner-design instance."""
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    assert_catalog_item,
    create_catalog_item_payload, create_customer_payload, create_order_payload,
    create_wallet_adjustment_payload,
    TEST_USERS, make_customer_headers,
)

ADMIN = TEST_USERS["admin_headers"]


def test_create_catalog_item_success(api):
    """PRD 3.1: "A `CatalogAdmin` registers a title edition by supplying its
    thirteen-digit `isbn13`, an `edition` number of at least 1, a `title`, and an
    `author`."
    PRD 4: "Creating a new resource returns HTTP 201".

    Design: Corner/entities/create_catalog_item_success
    """
    res = api.create_catalog(create_catalog_item_payload(isbn13="9780000000100", edition=2), ADMIN)
    item = validate_success(res, 201)
    assert_catalog_item(item)
    assert item["isbn13"] == "9780000000100"
    assert item["edition"] == 2


def test_get_order_nonexistent_returns_404(api):
    """PRD 2.9: "The first reference that does not resolve causes the request to be
    rejected with `ERR_RESOURCE_NOT_FOUND` (404) before any downstream business rule
    runs."

    Design: Corner/entities/get_order_nonexistent_returns_404
    """
    res = api.get_order(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_RESOURCE_NOT_FOUND", expected_status=404)


def test_create_order_missing_fulfillment_type_returns_400(api):
    """PRD 2.8: "Generic well-formedness — required fields present, correct types, enum
    values in range — is reported as `ERR_INVALID_REQUEST` (400) for any malformed POST
    body."
    PRD 3.3: "A `Customer` places an `Order` against a title by supplying the
    `catalog_item_id`, a `fulfillment_type` of `RENT`, `BUY`, or `EBOOK`, and — for
    rentals and ebooks — a `rental_term_days`."

    Design: Corner/entities/create_order_missing_fulfillment_type_returns_400
    """
    cat = validate_success(api.create_catalog(create_catalog_item_payload(), ADMIN), 201)
    cust = validate_success(api.create_customer(create_customer_payload(email="mf@x.com"), ADMIN), 201)
    headers = make_customer_headers(cust["id"])
    res = api.create_order({"catalog_item_id": cat["id"], "rental_term_days": 90}, headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_customer_wallet_credit_cents_computed(api):
    """PRD 2.6: "A customer's `wallet_credit_cents` is always the exact sum of the
    `amount_cents` of every `WalletTransaction` whose `customer_id` is that customer; it
    is recomputed on every ledger append and is order-independent."

    Design: Corner/entities/customer_wallet_credit_cents_computed
    """
    cust = validate_success(api.create_customer(create_customer_payload(email="wc@x.com"), ADMIN), 201)
    validate_success(api.create_wallet_adjustment(
        cust["id"], create_wallet_adjustment_payload(5000), ADMIN), 201)
    reread = validate_success(api.get_customer(cust["id"], ADMIN), 200)
    assert reread["wallet_credit_cents"] == 5000, reread["wallet_credit_cents"]


def test_catalog_duplicate_edition_returns_409(api):
    """PRD 3.1: "The combination of `isbn13` and `edition` must be unique; registering a
    duplicate pair is rejected with `ERR_DUPLICATE_EDITION`."

    Design: Corner/entities/catalog_duplicate_edition_returns_409
    """
    validate_success(api.create_catalog(
        create_catalog_item_payload(isbn13="9780000000102", edition=1), ADMIN), 201)
    res = api.create_catalog(
        create_catalog_item_payload(isbn13="9780000000102", edition=1, rental_base_cents=5000), ADMIN)
    validate_error(res, "ERR_DUPLICATE_EDITION", expected_status=409)


def test_order_invalid_term_for_rent_returns_422(api):
    """PRD 3.3: "a `RENT` order's `rental_term_days` must be one of 30, 60, 90, or 120;
    an `EBOOK` order must supply `rental_term_days`; and a `BUY` order must not supply it
    at all — any violation is `ERR_INVALID_TERM`."

    Design: Corner/entities/order_invalid_term_for_rent_returns_422
    """
    cat = validate_success(api.create_catalog(create_catalog_item_payload(), ADMIN), 201)
    cust = validate_success(api.create_customer(create_customer_payload(email="it@x.com"), ADMIN), 201)
    headers = make_customer_headers(cust["id"])
    res = api.create_order(create_order_payload(cat["id"], "RENT", rental_term_days=45), headers)
    validate_error(res, "ERR_INVALID_TERM", expected_status=422)
