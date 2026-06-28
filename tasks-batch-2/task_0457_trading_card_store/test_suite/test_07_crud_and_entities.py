"""Entity creation defaults, required-field and enum validation, not-found, listing
envelope, computed-field protection, and ledger immutability.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    create_customer,
    create_customer_payload, create_inventory_item_payload,
    ApiErrorId, TEST_USERS,
)

SM = TEST_USERS["store_manager_headers"]


def test_create_customer_returns_defaults(api):
    """PRD §3.1: "A newly created customer starts with `store_credit_balance_cents`
    of 0, `lifetime_spend_cents` of 0, a `loyalty_tier` of `BRONZE`, and a `status`
    of `ACTIVE`."
    PRD §2.5: "`version` — a system-managed integer that starts at its initial value
    on creation"

    Design: Corner/entities/create_customer_returns_defaults
    """
    res = api.create_customer(
        create_customer_payload(display_name="Fresh", email="fresh@x.com"), SM)
    cust = validate_success(res, 201)
    assert cust["store_credit_balance_cents"] == 0
    assert cust["lifetime_spend_cents"] == 0
    assert cust["loyalty_tier"] == "BRONZE"
    assert cust["status"] == "ACTIVE"
    assert cust["version"] == 1


def test_create_customer_missing_email_rejected(api):
    """PRD §3.1: "A store manager onboards a new patron by supplying a `display_name`
    and an `email`; the email is unique across customers."
    PRD §2.9: "the request body is validated for required, well-typed, valid-enum
    fields, failing with `ERR_INVALID_REQUEST` (HTTP 400)"

    Design: Corner/entities/create_customer_missing_required_field
    """
    res = api.create_customer({"display_name": "NoEmail"}, SM)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_customer_not_found(api):
    """PRD §2.4: "the system validates the identifiers left to right and rejects the
    request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that
    does not resolve to an existing resource"

    Design: Corner/entities/get_customer_not_found
    """
    res = api.get_customer("00000000-0000-4000-8000-000000000abc", SM)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_list_customers_pagination_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/list_customers_pagination_envelope
    """
    create_customer("L1", "l1@x.com")
    create_customer("L2", "l2@x.com")
    data, meta = validate_paginated(api.list_customers(SM, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_inventory_quantity_fields_default_zero(api):
    """PRD §3.2: "Every item tracks two counts that begin at 0: `quantity_on_hand`,
    the physical units the store owns, and `quantity_reserved`, the units committed
    to undelivered orders or grading holds."

    Design: Corner/entities/inventory_computed_quantity_fields_ignore_input
    """
    res = api.create_inventory_item(
        create_inventory_item_payload(title="Comp Card", product_kind="SEALED",
                                      market_price_cents=9999), SM)
    item = validate_success(res, 201)
    assert item["quantity_on_hand"] == 0
    assert item["quantity_reserved"] == 0


def test_inventory_invalid_product_kind_rejected(api):
    """PRD §3.2: "each created by a store manager with a `title`, a `product_kind` of
    either `SINGLE` or `SEALED`"
    PRD §2.9: "the request body is validated for required, well-typed, valid-enum
    fields, failing with `ERR_INVALID_REQUEST` (HTTP 400)"

    Design: Corner/entities/inventory_invalid_enum_product_kind
    """
    res = api.create_inventory_item(
        {"title": "Bad", "product_kind": "FOIL", "market_price_cents": 100}, SM)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_ledger_row_carries_only_id_and_created_at(api):
    """PRD §2.5: "A ledger row carries only `id` and `created_at`; it has no
    `updated_at` and no `version`, because rows are never modified after they are
    written."
    PRD §3.1: "a store manager seeds a customer's wallet by recording a credit
    adjustment, which appends a ledger row with `reason` `MANUAL_ADJUSTMENT` and a
    signed `delta_cents`"

    Design: Corner/entities/ledger_immutable_only_id_and_created_at
    """
    cust = create_customer("Led", "led@x.com")
    validate_success(api.create_credit_adjustment(cust["id"], {"delta_cents": 1000}, SM), 201)
    rows, _ = validate_paginated(api.list_ledger(cust["id"], SM))
    assert len(rows) == 1
    row = rows[0]
    assert row["delta_cents"] == 1000
    assert row["reason"] == "MANUAL_ADJUSTMENT"
    assert "version" not in row, "append-only ledger row must not carry version"
    assert "updated_at" not in row, "append-only ledger row must not carry updated_at"
