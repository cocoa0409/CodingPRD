"""Envelope shape, pagination defaults, listing reachability."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    SALES,
    api_client,
    assert_product,
    create_product_payload,
    create_retailer_payload,
    get_success_data,
    is_valid_uuid,
    setup_guide,
    setup_retailer,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_success_envelope_shape_object(api, admin_headers):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources." and "The `api_request_id` is a server-generated
    unique identifier for the request that starts with `req_`."

    Design: Corner/endpoints/success_envelope_shape
    """
    resp = api_client.create_product(create_product_payload(sku="P1"), admin_headers)
    body = resp.json()
    assert body.get("response_type") == "object"
    assert isinstance(body.get("meta", {}).get("api_request_id"), str)
    assert body["meta"]["api_request_id"].startswith("req_")
    data = validate_success(resp, expected_status=201)
    assert_product(data)


def test_pagination_defaults_on_products(api, admin_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter skips a number of items from the start of the result set and
    defaults to 0." and "Paginated list responses include `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response envelope."

    Design: Corner/endpoints/pagination_defaults_on_products
    """
    for i in range(1, 13):
        sku = f"S{i:02d}"
        get_success_data(api_client.create_product(create_product_payload(sku=sku), admin_headers))
    resp = api_client.list_products(admin_headers)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 12
    assert meta["has_more"] is True
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert len(data) == 10


def test_fk_reverse_order_guides_listing(api, admin_headers, sales_rep_headers):
    """PRD §4: "GET /retailers/{id}/order-guides — List a retailer's order guides"
    returns that retailer's guides.

    Design: Corner/endpoints/fk_reverse_order_guides_listing
    """
    retailer, _ = setup_retailer()
    guide = setup_guide(retailer_id=retailer["id"], lines=[])
    resp = api_client.list_retailer_order_guides(retailer["id"], sales_rep_headers)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert data[0]["id"] == guide["id"]


def test_fk_reverse_invoice_payments_listing(api, credit_manager_headers):
    """PRD §4: "GET /invoices/{id}/payments — List an invoice's payments"
    returns the payments applied to that invoice.

    Design: Corner/endpoints/fk_reverse_invoice_payments_listing
    """
    from test_helpers import setup_invoiced_order

    base = setup_invoiced_order([{"sku": "P1", "cases_qty": 50, "split_units_qty": 0}], fuel_doe=3.00)
    invoice = base["invoice"]
    pay = get_success_data(api_client.apply_payment(
        invoice["id"], {"amount_cents": 20000, "method": "CHECK"}, credit_manager_headers,
    ))
    resp = api_client.list_invoice_payments(invoice["id"], credit_manager_headers)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert data[0]["id"] == pay["id"]
    assert data[0]["amount_cents"] == 20000
