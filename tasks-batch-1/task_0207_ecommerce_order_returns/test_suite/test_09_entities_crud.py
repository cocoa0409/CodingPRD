"""Entity creation, defaults, snapshots, existence, immutability (PRD §2 / §3.1–§3.2).

Corner queue: entities (creation, defaults, computed snapshot, required fields,
type constraints, parent existence, listing, immutability).
"""
from test_helpers import (
    fixtures as fx,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    make_customer_headers,
    create_product_payload,
    create_warehouse_payload,
    create_order_line_payload,
    credit_adjustment_payload,
)


def test_create_product_returns_201_with_fields_and_defaults(api):
    """PRD §3.1: "an optional restocking_fee_bps also in basis points and defaulting
    to 0 (constrained to the inclusive range from 0 to 10000), a return_window_days
    count (may not be negative) governing how long after delivery a return may be
    opened, and an optional final_sale flag defaulting to false."
    PRD §2.4: "The version field is an integer that starts at its initial value and
    increments by one with every mutation of the resource".

    Design: Corner/entities/create_product_returns_201_with_all_fields
    """
    resp = api.create_product(
        create_product_payload(sku="PX-201", title="PX", unit_price_cents=1999,
                               tax_rate_bps=700, return_window_days=14), fx.ADMIN)
    data = validate_success(resp, 201)
    assert data["unit_price_cents"] == 1999
    assert data["tax_rate_bps"] == 700
    assert data["return_window_days"] == 14
    assert data["version"] == 1
    assert data["restocking_fee_bps"] == 0, "restocking_fee_bps defaults to 0"
    assert data["final_sale"] is False, "final_sale defaults to false"


def test_get_product_not_found_returns_404(api):
    """PRD §2.8: "the system validates the identifiers left to right and rejects the
    request with ERR_NOT_FOUND (HTTP 404) at the first identifier in the path that
    does not resolve to an existing resource".

    Design: Corner/entities/get_product_not_found_returns_404
    """
    resp = api.get_product(NON_EXISTENT_UUID, fx.ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_product_missing_required_field_returns_invalid_request(api):
    """PRD §2.9: "The shape of the request body — required fields present, correct
    types, valid enum members — is checked fifth, yielding ERR_INVALID_REQUEST (HTTP
    400)."

    Design: Corner/entities/create_product_missing_required_field_returns_invalid_request
    """
    resp = api.create_product(
        {"sku": "PNO", "title": "PNO", "tax_rate_bps": 700, "return_window_days": 14},
        fx.ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_warehouse_accepts_returns_defaults_true(api):
    """PRD §3.1: "an optional accepts_returns flag defaulting to true that governs
    whether restocked returns may be routed back to it."

    Design: Corner/entities/create_warehouse_accepts_returns_default_true
    """
    resp = api.create_warehouse(
        create_warehouse_payload(code="WD-DEF", name="Def", fulfillment_priority=1),
        fx.ADMIN)
    data = validate_success(resp, 201)
    assert data["accepts_returns"] is True


def test_order_line_snapshots_product_price(api):
    """PRD §3.2: "At the moment a line is added, the product's current price and tax
    rate are snapshotted onto the line as unit_price_cents_snapshot and
    tax_rate_bps_snapshot, immunizing the line against any later catalog edits."

    Design: Corner/entities/order_line_price_snapshot_immune_to_later_catalog_edit
    """
    customer = fx.create_customer()
    product = fx.create_product(unit_price_cents=1000, tax_rate_bps=0, return_window_days=30)
    order = fx.create_cart(customer["id"])
    line = fx.add_line(order["id"], customer["id"], product["id"], 1)
    assert line["unit_price_cents_snapshot"] == 1000


def test_create_order_line_qty_zero_returns_validation(api):
    """PRD §2.9: "A generic business-rule violation not covered by a more specific
    code — such as a negative promo_flat_cents or a quantity below one — is reported
    as ERR_VALIDATION (HTTP 422)."

    Design: Corner/entities/create_order_line_invalid_qty_zero_returns_validation
    """
    customer = fx.create_customer()
    product = fx.create_product(unit_price_cents=1000, tax_rate_bps=0, return_window_days=30)
    order = fx.create_cart(customer["id"])
    headers = make_customer_headers(customer["id"])
    resp = api.add_order_line(
        order["id"], create_order_line_payload(product["id"], 0), headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_order_line_requires_existing_parent_order(api):
    """PRD §2.8: "the system validates the identifiers left to right and rejects the
    request with ERR_NOT_FOUND (HTTP 404) at the first identifier in the path that
    does not resolve to an existing resource, before examining anything further to its
    right."

    Design: Corner/entities/order_line_requires_valid_parent_order
    """
    product = fx.create_product(unit_price_cents=1000, tax_rate_bps=0, return_window_days=30)
    resp = api.add_order_line(
        NON_EXISTENT_UUID, create_order_line_payload(product["id"], 1), fx.ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_list_customer_orders_pagination_envelope(api):
    """PRD §2.3: "List-based responses include the following fields in the meta
    object of the response envelope: limit, offset, total_count, and has_more."

    Design: Corner/entities/list_orders_pagination_envelope
    """
    customer = fx.create_customer()
    fx.create_cart(customer["id"])
    headers = make_customer_headers(customer["id"])
    resp = api.list_customer_orders(customer["id"], headers,
                                    params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_list_order_lines_reverse_reachability(api):
    """PRD §3.9: "An order's lines, shipments, returns, and refunds; a return's lines
    and refunds; a refund's credit entries; a reservation's committing shipment lines"
    PRD §2.3: "List-based responses include the following fields in the meta object of
    the response envelope: limit, offset, total_count, and has_more."

    Design: Corner/endpoints/list_order_lines_filtered_reverse_reachability
    """
    customer = fx.create_customer()
    p1 = fx.create_product(unit_price_cents=1000, tax_rate_bps=0, return_window_days=30)
    p2 = fx.create_product(unit_price_cents=2000, tax_rate_bps=0, return_window_days=30)
    order = fx.create_cart(customer["id"])
    fx.add_line(order["id"], customer["id"], p1["id"], 1)
    fx.add_line(order["id"], customer["id"], p2["id"], 1)
    headers = make_customer_headers(customer["id"])
    resp = api.list_order_lines(order["id"], headers)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2


def test_credit_ledger_entry_has_no_version(api):
    """PRD §2.4: "A CreditLedgerEntry is an immutable audit record: it carries only
    id and created_at. It has no updated_at and no version, because once written a
    ledger entry is never modified."

    Design: Corner/entities/credit_ledger_entry_is_immutable_no_version
    """
    customer = fx.create_customer()
    fx.get_success_data(api.create_credit_adjustment(
        customer["id"], credit_adjustment_payload(500, "ADMIN_ADJUSTMENT"), fx.ADMIN))
    resp = api.list_customer_credit_entries(customer["id"], fx.ADMIN)
    data, _ = validate_paginated(resp)
    assert len(data) == 1
    entry = data[0]
    assert "version" not in entry, "CreditLedgerEntry carries no version"
    assert "updated_at" not in entry, "CreditLedgerEntry carries no updated_at"
    assert entry["amount_cents"] == 500
    assert entry["kind"] == "ADMIN_ADJUSTMENT"
