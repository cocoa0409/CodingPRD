"""Practice onboarding, catalog management, response envelope, and auth baseline."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    is_valid_uuid,
    assert_practice,
    assert_product,
    create_practice_payload,
    create_product_payload,
    create_order_payload,
    make_practice_manager_headers,
    ApiErrorId,
    NON_EXISTENT_UUID,
)


def test_practice_create_applies_defaults(api, admin_headers):
    """PRD §3.1: "optionally its commercial `practice_tier` — `STANDARD`, `PREMIER`,
    or `ELITE`, defaulting to `STANDARD`" and "The onboarding payload may also carry
    `regulated_license_expiry` (defaulting to null) and `sterilization_compliant`
    (defaulting to false). A new practice starts with `status` `ACTIVE`, and its
    `credit_available_cents` is initialized to its `credit_limit_cents`."

    Design: Corner/entities/practice_create_applies_defaults
    """
    res = api.create_practice(
        create_practice_payload(name="P Def", region="R1", credit_limit_cents=500000),
        admin_headers,
    )
    practice = validate_success(res, 201)
    assert_practice(practice)
    assert practice["status"] == "ACTIVE"
    assert practice["practice_tier"] == "STANDARD"
    assert practice["sterilization_compliant"] is False
    assert practice.get("regulated_license_expiry") is None
    assert practice["credit_available_cents"] == 500000, (
        f"credit_available_cents must initialize to credit_limit_cents, got "
        f"{practice['credit_available_cents']}"
    )
    assert is_valid_uuid(practice["id"]), "id must be a server-minted UUID"


def test_product_create_and_retrieval(api, admin_headers):
    """PRD §3.1: "Creating a product requires a unique `sku`, a display `name`, a `kind`
    of `CONSUMABLE`, `EQUIPMENT`, `PART`, or `REGULATED`, a `unit_price_cents` catalog
    price, and the `manufacturer` name that later serves as the rebate counterparty."

    Design: Corner/entities/product_create_and_retrieval
    """
    payload = create_product_payload(
        sku="RG-9",
        name="Amalgam",
        kind="REGULATED",
        unit_price_cents=2500,
        manufacturer="M",
        max_qty_per_order=4,
        sterilization_cycle_required=True,
        warranty_months=0,
    )
    product = validate_success(api.create_product(payload, admin_headers), 201)
    assert_product(product)

    fetched = validate_success(api.get_product(product["id"], admin_headers), 200)
    assert fetched["sku"] == "RG-9"
    assert fetched["kind"] == "REGULATED"
    assert fetched["sterilization_cycle_required"] is True
    assert fetched["unit_price_cents"] == 2500
    assert fetched["max_qty_per_order"] == 4
    assert fetched["manufacturer"] == "M"


def test_practice_create_missing_credit_limit_returns_invalid_request(api, admin_headers):
    """PRD §2.8: "Request shape comes fourth: required fields present, enum members
    valid, quantities strictly positive, datetimes well-formed, a window's end strictly
    after its start, and no client-supplied order kind of `AUTO` — violations yield
    `ERR_INVALID_REQUEST` (400)."
    PRD §3.1: onboarding supplies "its `credit_limit_cents` (the maximum open-order
    credit, which must be at least zero)".

    Design: Corner/entities/practice_create_missing_required_credit_limit_returns_invalid_request
    """
    res = api.create_practice({"name": "P Bad", "region": "R1"}, admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_product_create_invalid_enum_returns_invalid_request(api, admin_headers):
    """PRD §2.8: "Request shape comes fourth: required fields present, enum members
    valid, quantities strictly positive, datetimes well-formed, a window's end strictly
    after its start, and no client-supplied order kind of `AUTO` — violations yield
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/product_create_invalid_enum_returns_invalid_request
    """
    res = api.create_product(
        create_product_payload(sku="X-1", kind="WIDGET", unit_price_cents=100),
        admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_order_get_nonexistent_returns_not_found(api, admin_headers):
    """PRD §2.8: "Existence comes third: every identifier in the path and every foreign
    key in the body must reference an existing resource, otherwise
    `ERR_RESOURCE_NOT_FOUND` (404)".

    Design: Corner/entities/order_get_nonexistent_returns_not_found
    """
    res = api.get_order(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


def test_response_envelope_object_shape(api, admin_headers):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`." and "The `response_type` is either "object" for a
    single resource or "array" for a list of resources."

    Design: Corner/endpoints/response_envelope_object_shape
    """
    practice = validate_success(
        api.create_practice(
            create_practice_payload(name="P Env", region="R1", credit_limit_cents=100000),
            admin_headers,
        ),
        201,
    )
    res = api.get_practice(practice["id"], admin_headers)
    data = validate_success(res, 200)
    body = res.json()
    assert "meta" in body and "response_type" in body and "data" in body
    assert body["meta"].get("api_request_id", "").startswith("req_")
    assert body["meta"].get("api_request_timestamp"), "api_request_timestamp must be populated"
    assert body["response_type"] == "object"
    assert data["id"] == practice["id"]


def test_missing_auth_headers_returns_unauthenticated(api, admin_headers):
    """PRD §2.8: "Authentication comes first: missing or unknown headers yield
    `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/errors/missing_auth_headers_returns_unauthenticated
    """
    practice = validate_success(
        api.create_practice(
            create_practice_payload(name="P Au", region="R1", credit_limit_cents=100000),
            admin_headers,
        ),
        201,
    )
    res = api.get_practice(practice["id"], headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_practice_manager_cannot_create_products(api, admin_headers):
    """PRD §2.1: "A request whose role is not permitted on the targeted endpoint, or that
    fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /api/products is authorized for DistributionAdmin only.

    Design: Corner/validations/practice_manager_cannot_create_products
    """
    practice = validate_success(
        api.create_practice(
            create_practice_payload(name="P X", region="R1", credit_limit_cents=1000000),
            admin_headers,
        ),
        201,
    )
    res = api.create_product(
        create_product_payload(sku="Z-1", name="Z", kind="CONSUMABLE", unit_price_cents=100),
        make_practice_manager_headers(practice["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
