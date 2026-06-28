"""List endpoints (pagination envelope, member filtering) and immediate
consistency of computed pricing on the pay response."""
from test_helpers import (
    validate_success, validate_paginated,
    TEST_USERS, make_member_headers,
    create_title_payload, create_sales_order_payload, create_order_line_payload,
    make_member, make_title, receive_stock,
)

BOOKSELLER = TEST_USERS["bookseller_headers"]


def test_list_titles_pagination_envelope(api):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."
    PRD §2.3: "If not provided, it defaults to 10, with a minimum of 1 and a
    maximum of 100."

    Design: Corner/endpoints/list_titles_pagination_envelope
    """
    validate_success(
        api.create_title(create_title_payload(isbn13="9780000133334", name="A",
                                              list_price_cents=1000), BOOKSELLER),
        expected_status=201,
    )
    validate_success(
        api.create_title(create_title_payload(isbn13="9780000144445", name="B",
                                              list_price_cents=1200), BOOKSELLER),
        expected_status=201,
    )
    resp = api.list_titles(BOOKSELLER)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10


def test_list_orders_filtered_by_member(api):
    """PRD §4 (endpoint): `GET /sales-orders` "List sales orders".
    PRD §3.4: "A `Member` (acting on their own account), a `Bookseller`, or a
    `StoreAdmin` opens an order for a member by supplying that member's
    `member_id`" — the order records `member_id`, so a member filter returns only
    that member's orders.

    Design: Corner/endpoints/list_orders_filtered_by_member
    """
    member = make_member()
    mh = make_member_headers(member["id"])
    validate_success(
        api.create_sales_order(create_sales_order_payload(member["id"]), mh),
        expected_status=201,
    )
    resp = api.list_sales_orders(mh, params={"member_id": member["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert all(o["member_id"] == member["id"] for o in data)


def test_pay_response_shows_pricing_immediately(api):
    """PRD §3.4: "On a successful payment the system prices the order (the
    order-pricing calculation below), computes provisional loyalty points".
    PRD §3.4: "**Paying** an order moves `payment_status` from `UNPAID` to
    `PAID`".

    Design: Corner/consistency_model/pay_response_shows_pricing_immediately
    """
    member = make_member()
    title = make_title(list_price_cents=1000)
    receive_stock(title["id"], 1)
    mh = make_member_headers(member["id"])
    order = validate_success(
        api.create_sales_order(create_sales_order_payload(member["id"]), mh),
        expected_status=201,
    )
    api.create_order_line(order["id"], create_order_line_payload(title["id"], 1), mh)
    resp = api.pay_order(order["id"], mh)
    data = validate_success(resp)
    assert data["payment_status"] == "PAID"
    assert data["net_paid_cents"] == 1000
