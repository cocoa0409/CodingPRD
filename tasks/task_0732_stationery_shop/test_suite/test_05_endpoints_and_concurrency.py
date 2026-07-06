"""Endpoints CRUD behaviors, pagination, OCC stale version, immediate consistency."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    api_client, TEST_USERS, NON_EXISTENT_UUID,
    setup_cart_order_with_line, setup_deposit_pending,
    create_customer, create_designer, create_paper_stock, create_finish_option,
    create_event_package, create_design_for, create_cart_order_for,
    add_line_item_to_cart,
    make_customer_headers,
    create_line_item_payload,
)


def test_list_orders_returns_paginated_envelope_defaults(api, shop_admin_headers):
    """PRD §2.3: "The limit parameter specifies the maximum number of items to return; it
    defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.2: "The api_request_id is a server-generated unique identifier for the request
    that starts with req_."

    Design: Corner/endpoints/list_orders_pagination_defaults
    """
    customer = create_customer()
    paper = create_paper_stock()
    finish = create_finish_option()
    pkg = create_event_package()
    design = create_design_for(customer, paper, finish, pkg)
    cust_headers = make_customer_headers(customer["id"])
    for _ in range(3):
        get_success_data(api.create_order(
            {"customer_id": customer["id"], "design_id": design["id"]}, cust_headers,
        ))
    data, meta = validate_paginated(api.list_orders(shop_admin_headers,
                                                    params={"customer_id": customer["id"]}))
    assert len(data) <= 10


def test_delete_line_item_bumps_order_version_and_zeroes_subtotal(api):
    """PRD §3.3: "Every successful add or delete of a line item recomputes Order.subtotal_cents
    (the sum of LineItem.line_price_cents across all live lines on the order) and
    Order.total_cents, and increments Order.version by one; a delete of a line item on a CART
    order is a no-body operation returning 204."

    Design: Corner/endpoints/delete_line_item_bumps_order_version
    """
    bundle = setup_cart_order_with_line(quantity=150)
    customer, order, line = bundle["customer"], bundle["order"], bundle["line_item"]
    version_before_delete = order["version"]
    cust_headers = make_customer_headers(customer["id"])
    del_res = api.delete_line_item(order["id"], line["id"], cust_headers)
    assert del_res.status_code == 204, f"expected 204, got {del_res.status_code}"
    # Read back
    order_after = get_success_data(api.get_order(order["id"], cust_headers))
    assert order_after["version"] == version_before_delete + 1
    assert order_after["subtotal_cents"] == 0


def test_confirm_visible_immediately_in_same_response(api):
    """PRD §3.5: "When the customer is satisfied with the cart, they confirm the order,
    moving Order.status from CART to DEPOSIT_PENDING."
    PRD §3.5: "the deposit due is that base multiplied by EventPackage.deposit_pct,
    rounded half-up to a whole number of cents."

    Design: Corner/consistency_model/immediate_consistency_confirm_visible_in_same_response
    """
    bundle = setup_cart_order_with_line(quantity=150)
    customer, order = bundle["customer"], bundle["order"]
    cust_headers = make_customer_headers(customer["id"])
    res = api.confirm_order(order["id"], cust_headers)
    confirmed = validate_success(res, 200)
    assert confirmed["status"] == "DEPOSIT_PENDING"
    # subtotal 82500 (500*150*0.9 + 100*150), deposit_pct 0.5 → 41250
    assert confirmed["deposit_due_cents"] == 41250


def test_add_line_item_with_stale_expected_version_returns_stale_version(api):
    """PRD §2.7: "If, at the moment the server evaluates the request,
    expected_order_version does not equal the current Order.version — because another writer
    has since added, removed, or repriced a line on the same order and therefore advanced
    Order.version — the create is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_version_on_line_item_add_returns_412
    """
    customer = create_customer()
    paper = create_paper_stock()
    finish = create_finish_option()
    pkg = create_event_package()
    design = create_design_for(customer, paper, finish, pkg)
    order = create_cart_order_for(customer, design)
    stale_version = order["version"]
    cust_headers = make_customer_headers(customer["id"])
    # First add advances version
    first_payload = create_line_item_payload(
        paper_stock_id=paper["id"], finish_option_id=finish["id"],
        quantity=100, expected_order_version=stale_version,
    )
    get_success_data(api.add_line_item(order["id"], first_payload, cust_headers))
    # Second add uses stale version
    second_payload = create_line_item_payload(
        paper_stock_id=paper["id"], finish_option_id=finish["id"],
        quantity=200, expected_order_version=stale_version,
    )
    res = api.add_line_item(order["id"], second_payload, cust_headers)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_rush_zero_days_returns_rush_infeasible(api):
    """PRD §3.4: "The system computes the number of whole days between rush_deadline and
    the current UTC time, and rejects the request with ERR_RUSH_INFEASIBLE unless that
    number is at least three and strictly less than fourteen: a deadline fourteen or more
    days out is too far away for the rush tier to apply, and a deadline fewer than three
    days out is infeasible."

    Design: Corner/cross_cutting/rush_threshold_precise_zero_days_returns_infeasible
    """
    from test_helpers import set_clock
    set_clock("2026-04-01T00:00:00Z")
    bundle = setup_cart_order_with_line(quantity=150)
    cust_headers = make_customer_headers(bundle["customer"]["id"])
    # rush_deadline == current_utc → days=0 → infeasible
    res = api.apply_rush(bundle["order"]["id"],
                         {"rush_deadline": "2026-04-01T00:00:00Z"}, cust_headers)
    validate_error(res, "ERR_RUSH_INFEASIBLE")
