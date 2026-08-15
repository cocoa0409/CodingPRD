"""List endpoints: pagination envelope, filters, and reverse FK listings
(PRD §2.2, §2.3, §3.7)."""
import pytest
from test_helpers import (
    validate_success, validate_paginated,
    setup_book, create_draft_order, submit_site_check, file_report,
    approve_application, get_only_application, record_order_payment,
    complete_ready_order,
    DEPOSIT_10X12_WINDOW, PERMIT_FEE_120_SQFT,
)
from test_helpers import TEST_USERS

SALES = TEST_USERS["sales_rep_headers"]
PERMIT = TEST_USERS["permit_coordinator_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


def test_orders_list_pagination_and_filter(api):
    """PRD §2.3: "`limit` sets the maximum number of items returned; it defaults to 10,
    with a minimum of 1 and a maximum of 100. `offset` sets how many items to skip and
    defaults to 0. Unless stated otherwise, every list is sorted by `created_at` in
    ascending order, and the `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`. The order listing additionally accepts the optional
    filters `customer_id`, `model_id`, `jurisdiction_id`, and `status` alongside `limit`
    and `offset`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/endpoints/orders_list_pagination_and_filter
    """
    jur, model, cust = setup_book()
    create_draft_order(cust["id"], model["id"], jur["id"], width_ft=8, depth_ft=8)
    create_draft_order(cust["id"], model["id"], jur["id"], width_ft=10, depth_ft=12)

    data, meta = validate_paginated(
        api.list_orders(SALES, params={"customer_id": cust["id"], "limit": 1, "offset": 0})
    )
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert isinstance(meta.get("api_request_id"), str)
    assert isinstance(meta.get("api_request_timestamp"), str)
    assert all(row["customer_id"] == cust["id"] for row in data)


def test_reverse_fk_lists_resolve_children(api):
    """PRD §3.7: "An order produces at most one contract, so reading the contract through
    its order returns an array containing zero or one element."
    PRD §3.6: "The first payment recorded against an order takes a `kind` of `DEPOSIT`;
    every later one takes a `kind` of `BALANCE`."
    PRD §2.3: "the `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/fk_reverse_lists_resolve_children
    """
    jur, model, cust = setup_book()
    order = create_draft_order(cust["id"], model["id"], jur["id"], options=["WINDOW"])
    asm = submit_site_check(order["id"])
    file_report(asm["id"])
    app = approve_application(get_only_application(order["id"])["id"])
    record_order_payment(order["id"], DEPOSIT_10X12_WINDOW, "dep-1")
    completed = complete_ready_order(order)  # already READY; deposit recorded above
    assert completed["status"] == "COMPLETED"

    asms, meta_asm = validate_paginated(api.list_order_site_assessments(order["id"], SALES))
    assert meta_asm["total_count"] == 1
    assert asms[0]["id"] == asm["id"]
    assert asms[0]["status"] == "REPORTED"
    assert asms[0]["verdict"] == "SUITABLE"

    apps, meta_app = validate_paginated(api.list_order_permit_applications(order["id"], SALES))
    assert meta_app["total_count"] == 1
    assert apps[0]["status"] == "APPROVED"
    assert apps[0]["fee_cents"] == PERMIT_FEE_120_SQFT
    assert apps[0]["jurisdiction_version"] == jur["version"]

    payments, meta_pay = validate_paginated(api.list_order_payments(order["id"], SALES))
    assert meta_pay["total_count"] == 1
    assert payments[0]["kind"] == "DEPOSIT"
    assert payments[0]["amount_cents"] == DEPOSIT_10X12_WINDOW

    # A cash order never has a contract to read through its order.
    contracts = validate_success(api.get_order_rto_contract(order["id"], SALES), 200)
    assert isinstance(contracts, list) and len(contracts) == 0

    tickets, meta_tick = validate_paginated(api.list_order_service_tickets(order["id"], SALES))
    assert meta_tick["total_count"] == 0

    jur_apps, meta_jur = validate_paginated(
        api.list_jurisdiction_permit_applications(jur["id"], PERMIT)
    )
    assert meta_jur["total_count"] == 1
    assert jur_apps[0]["id"] == app["id"]
