"""Entity CRUD, defaults, type/validation, and immutability — breadth coverage (queue B, entities)."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    assert_order,
    assert_payment,
    make_customer_headers,
    make_manager_headers,
    make_anonymous_headers,
    fixtures,
    factories,
)

MANAGER = make_manager_headers()
ANON = make_anonymous_headers()


def test_create_order_returns_201_with_defaults(api):
    """PRD §3.2: "A new order begins in `production_status` `DRAFT` and `payment_status`
    `UNPAID`, with `version` 1 and every computed total at its default."

    Design: Corner/entities/create_order_returns_201_with_defaults
    """
    customer = fixtures.register_customer()
    resp = api.create_order(
        factories.create_order_payload(customer["id"]), make_customer_headers(customer["id"])
    )
    data = validate_success(resp, 201)
    assert_order(data)
    assert data["production_status"] == "DRAFT"
    assert data["payment_status"] == "UNPAID"
    assert data["version"] == 1
    assert data["line_count"] == 0


def test_get_order_not_found_returns_404(api):
    """PRD §2.6: "The first identifier in the path that names a non-existent record —
    whether an `order_id`, an `order_line_id`, a proof, a `component_id`, a
    `catalog_product_id`, a `promo_code_id`, a customer, a fulfillment, or a component
    allocation — causes the request to be rejected with `ERR_NOT_FOUND` before any deeper
    identifier or body field is examined."

    Design: Corner/entities/get_order_not_found_returns_404
    """
    customer = fixtures.register_customer()
    resp = api.get_order(
        "00000000-0000-4000-8000-000000000000", make_customer_headers(customer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_order_missing_due_date_returns_invalid_request(api):
    """PRD §2.7: "then structural validity of the body — required fields present, correct
    types, valid enum members, `quantity` at least 1, amounts not negative
    (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_order_missing_due_date_returns_invalid_request
    """
    customer = fixtures.register_customer()
    payload = {"customer_id": customer["id"], "service_level": "STANDARD"}
    resp = api.create_order(payload, make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_order_bad_service_level_enum_returns_invalid_request(api):
    """PRD §2.7: "then structural validity of the body — required fields present, correct
    types, valid enum members, `quantity` at least 1, amounts not negative
    (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_order_bad_service_level_enum_returns_invalid_request
    """
    customer = fixtures.register_customer()
    payload = factories.create_order_payload(customer["id"], service_level="OVERNIGHT")
    resp = api.create_order(payload, make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_line_default_quantity_engraving_text_empty(api):
    """PRD §3.2: "Each `OrderLine` names a `catalog_product_id`, a `quantity` of at least 1,
    an optional `engraving_text` (defaulting to an empty string, applied identically to
    every unit of the line), and an optional `include_logo` flag (defaulting to false)."

    Design: Corner/entities/create_line_default_quantity_engraving_text_empty
    """
    base = fixtures.setup_foundation(
        product_overrides={"engraving_price_per_char_cents": 50, "logo_setup_fee_cents": 2000},
        on_hand_qty=10,
    )
    order = fixtures.create_order(base["customer"])
    resp = api.add_line(
        order["id"],
        factories.create_line_payload(base["product"]["id"], quantity=1),
        make_customer_headers(base["customer"]["id"]),
    )
    data = validate_success(resp, 201)
    assert data["engraving_text"] == ""
    assert data["include_logo"] is False
    assert data["line_status"] == "PENDING"


def test_payment_entity_has_no_version_field_immutable(api):
    """PRD §2.4: "A `Payment` record carries only `id` and `created_at` — it has neither
    `updated_at` nor `version`, because a payment is an immutable event whose only later
    change is a status flip handled through its owning order."

    Design: Corner/entities/payment_entity_has_no_version_field_immutable
    """
    ctx = fixtures.setup_confirmed_order(
        product_overrides={"base_price_cents": 10000, "standard_lead_days": 3},
        on_hand_qty=10,
    )
    order, cust = ctx["order"], ctx["customer"]
    fixtures.pay(order, cust, order["deposit_due_cents"], "DEPOSIT")
    resp = api.list_payments(order["id"], make_customer_headers(cust["id"]))
    data, _meta = validate_paginated(resp)
    assert len(data) == 1
    assert_payment(data[0])
    assert data[0]["pay_status"] == "CAPTURED"
    assert "version" not in data[0]


def test_duplicate_customer_email_returns_duplicate_value(api):
    """PRD §3.1: "A unique-field collision — a second customer with the same `email` — is
    rejected with `ERR_DUPLICATE_VALUE`."

    Design: Corner/entities/duplicate_customer_email_returns_duplicate_value
    """
    email = factories.create_customer_payload()["email"]
    first = api.create_customer({"email": email, "full_name": "First"}, ANON)
    validate_success(first, 201)
    resp = api.create_customer({"email": email, "full_name": "Second"}, ANON)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VALUE.value)
