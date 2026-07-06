"""Corner queue — endpoints section."""
from test_helpers import (
    validate_success, validate_paginated, api_client,
    make_store_manager_headers, make_store_clerk_headers,
)
from test_helpers.fixtures import (
    set_clock, create_customer, create_sku_with_stock, create_sku, create_order,
)


def test_list_orders_filters_by_customer_id():
    """PRD §4 (endpoint description): "List Orders with optional
    customer_id filter"
    PRD §2.3: "Every list response sorts its resources by created_at in
    ascending order unless the endpoint description says otherwise."

    Design: Corner/endpoints/list_orders_by_customer_id_filter
    """
    set_clock("2026-06-15T10:00:00Z")
    cust_a = create_customer()
    cust_b = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=10)
    create_order(cust_a["id"], channel="IN_STORE",
                 lines=[{"sku_id": sku["id"], "qty": 1}])
    create_order(cust_a["id"], channel="IN_STORE",
                 lines=[{"sku_id": sku["id"], "qty": 1}])
    create_order(cust_b["id"], channel="IN_STORE",
                 lines=[{"sku_id": sku["id"], "qty": 1}])
    resp = api_client.list_orders(
        make_store_clerk_headers(), params={"customer_id": cust_a["id"]},
    )
    data, meta = validate_paginated(resp)
    assert len(data) == 2, (
        f"customer_id={cust_a['id']} filter should return 2 rows; got {len(data)}"
    )
    for row in data:
        assert row["customer_id"] == cust_a["id"], (
            f"filtered list must only include rows with matching customer_id; "
            f"got {row['customer_id']}"
        )


def test_list_skus_pagination_defaults_and_ordering():
    """PRD §2.3: "List endpoints accept the limit and offset query
    parameters. limit defaults to 10 when not provided; the minimum
    accepted value is 1 and the maximum is 100. offset defaults to 0
    and represents the number of leading items to skip. Every list
    response sorts its resources by created_at in ascending order unless
    the endpoint description says otherwise."

    Design: Corner/endpoints/pagination_defaults_and_limits_on_skus_list
    """
    for i in range(12):
        create_sku(sku_code=f"PAG-{i+1:02d}",
                   category="DECOR", unit_price_cents=100)
    # limit=5 → 5 rows, first is PAG-01 (oldest).
    resp = api_client.list_skus(
        make_store_manager_headers(), params={"limit": 5}
    )
    data, meta = validate_paginated(resp)
    assert len(data) == 5, f"limit=5 must return 5 rows; got {len(data)}"
    assert data[0]["sku_code"] == "PAG-01", (
        f"created_at ASC ordering — first row must be PAG-01; "
        f"got {data[0]['sku_code']}"
    )
