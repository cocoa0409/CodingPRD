"""Response envelope shape, pagination, and list filters (PRD §2.2, §2.3, §3.6)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_customer_headers,
    create_ingredient_payload, create_bin_payload,
    make_ingredient, make_bin, make_line, make_batch,
    setup_confirmed_order, get_customer, create_order_payload, confirm_order,
)

MM = TEST_USERS["mill_manager_headers"]


def test_bin_list_pagination_limit_offset(api):
    """PRD §2.3: "`limit` caps the number of items returned: it defaults to 10, accepts a minimum of 1, and is clamped at a maximum of 100."
    PRD §2.3: "The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/bin_list_pagination_limit_offset
    """
    for code in ("BIN-1", "BIN-2", "BIN-3"):
        make_bin(code, 50)

    page1, meta1 = validate_paginated(api.list_bins(MM, params={"limit": 2}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(api.list_bins(MM, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    page_default, meta_default = validate_paginated(api.list_bins(MM))
    assert meta_default["limit"] == 10, "default page size must be 10"
    assert len(page_default) == 3


def test_response_envelope_shape_on_success_and_error(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    PRD §3.1: "A `MillManager` registers an ingredient with a unique `code` (a duplicate is refused with `ERR_DUPLICATE_CODE`)"

    Design: Corner/endpoints/response_envelope_shape_on_success_and_error
    """
    corn = make_ingredient("CORN")

    ok = api.get_ingredient(corn["id"], MM)
    data = validate_success(ok, 200)
    body = ok.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert data["id"] == corn["id"]

    dup = api.create_ingredient(
        create_ingredient_payload("CORN", name="Duplicate corn"), MM)
    err = validate_error(dup, ApiErrorId.ERR_DUPLICATE_CODE)
    err_body = dup.json()
    assert err_body["response_type"] == "error"
    assert err_body["meta"]["api_request_id"]
    assert err_body["meta"]["api_request_timestamp"]
    assert err["message"].strip(), "error envelope must carry a human-readable message"


def test_list_filter_batches_by_order(api):
    """PRD §3.6: "Batch listings accept optional `order_id`, `line_id`, and `status` filters."

    Design: Corner/endpoints/list_filter_batches_by_order
    """
    ctx = setup_confirmed_order(tons=10, credit_limit_cents=5000000)
    # Second confirmed order for the same customer (fresh OCC version each time).
    order2 = get_success_data(api.create_order(
        create_order_payload(ctx["formula"]["id"], 10,
                             get_customer(ctx["customer"]["id"])["version"]),
        make_customer_headers(ctx["customer"]["id"])))
    order2 = confirm_order(order2, ctx["customer"]["id"])

    line = make_line("L1")
    b1 = make_batch(ctx["order"]["id"], line["id"], 5,
                    "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z")
    b2 = make_batch(order2["id"], line["id"], 5,
                    "2026-05-02T12:00:00Z", "2026-05-02T13:00:00Z")

    data1, meta1 = validate_paginated(api.list_batches(MM, params={"order_id": ctx["order"]["id"]}))
    assert [b["id"] for b in data1] == [b1["id"]]
    assert meta1["total_count"] == 1

    data2, meta2 = validate_paginated(api.list_batches(MM, params={"order_id": order2["id"]}))
    assert [b["id"] for b in data2] == [b2["id"]]
    assert meta2["total_count"] == 1

    data_all, meta_all = validate_paginated(api.list_batches(MM))
    assert meta_all["total_count"] == 2
    assert {b["id"] for b in data_all} == {b1["id"], b2["id"]}
