"""Response envelope, not-found sweep, pagination defaults, and FK reverse
reachability (PRD §2.2, §2.3, §2.5, §3.4, §4)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_distributor,
    create_distributor,
    create_route,
    create_store,
    make_driver_headers,
    set_clock,
    setup_delivered_order,
    approve_return,
    create_return,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)

TM = TEST_USERS["territory_manager_headers"]
DR = TEST_USERS["route_driver_headers"]


def test_error_envelope_shape(api, territory_manager_headers):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."

    Design: Corner/errors/error_envelope_shape
    """
    distributor = create_distributor(name="Dairy Dist EA", license_number="LIC-EA-1")

    err_resp = api.get_store(NON_EXISTENT_UUID, territory_manager_headers)
    assert err_resp.status_code == 404
    body = err_resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == ApiErrorId.ERR_STORE_NOT_FOUND
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
    assert body["meta"]["api_request_id"].startswith("req_")
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}

    ok_resp = api.get_distributor(distributor["id"], territory_manager_headers)
    data = validate_success(ok_resp, 200)
    assert ok_resp.json()["response_type"] == "object"
    assert ok_resp.json()["meta"]["api_request_id"].startswith("req_")
    assert_distributor(data)
    assert data["id"] == distributor["id"]


@pytest.mark.parametrize(
    "getter,error_id",
    [
        ("get_distributor", ApiErrorId.ERR_DISTRIBUTOR_NOT_FOUND),
        ("get_route", ApiErrorId.ERR_ROUTE_NOT_FOUND),
        ("get_driver", ApiErrorId.ERR_DRIVER_NOT_FOUND),
        ("get_store", ApiErrorId.ERR_STORE_NOT_FOUND),
        ("get_product", ApiErrorId.ERR_PRODUCT_NOT_FOUND),
        ("get_standing_par", ApiErrorId.ERR_PAR_NOT_FOUND),
        ("get_pricing_period", ApiErrorId.ERR_PRICING_PERIOD_NOT_FOUND),
        ("get_announcement", ApiErrorId.ERR_ANNOUNCEMENT_NOT_FOUND),
        ("get_trip", ApiErrorId.ERR_TRIP_NOT_FOUND),
        ("get_order", ApiErrorId.ERR_ORDER_NOT_FOUND),
        ("get_invoice", ApiErrorId.ERR_INVOICE_NOT_FOUND),
        ("get_return", ApiErrorId.ERR_RETURN_NOT_FOUND),
        ("get_credit_memo", ApiErrorId.ERR_CREDIT_MEMO_NOT_FOUND),
        ("get_route_sale_listing", ApiErrorId.ERR_LISTING_NOT_FOUND),
        ("get_merchandising_session", ApiErrorId.ERR_SESSION_NOT_FOUND),
    ],
)
def test_entity_get_not_found_sweep(api, territory_manager_headers, getter, error_id):
    """PRD §2.5: "(4) existence of every path- and body-referenced resource,
    producing the not-found error for the resource type in question —
    `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`,
    `ERR_STORE_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_PAR_NOT_FOUND`,
    `ERR_PRICING_PERIOD_NOT_FOUND`, `ERR_ANNOUNCEMENT_NOT_FOUND`,
    `ERR_TRIP_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`,
    `ERR_RETURN_NOT_FOUND`, `ERR_CREDIT_MEMO_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    or `ERR_SESSION_NOT_FOUND`"

    Design: Corner/entities/entity_get_not_found_sweep
    """
    set_clock("2026-08-01T00:00:00Z")
    resp = getattr(api, getter)(NON_EXISTENT_UUID, territory_manager_headers)
    validate_error(resp, error_id)


def test_pagination_defaults_and_offset(api, territory_manager_headers):
    """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum of
    100; `offset` defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/pagination_defaults_and_offset
    """
    distributor = create_distributor(name="Dairy Dist DA", license_number="LIC-DA-1")
    route = create_route(distributor["id"], route_code="R-DA")
    store_ids = []
    for i in range(1, 13):
        store = create_store(route["id"], distributor["id"], store_code=f"PG-{i:02d}")
        store_ids.append(store["id"])

    page1, meta1 = validate_paginated(api.list_route_stores(route["id"], territory_manager_headers))
    assert len(page1) == 10, f"default limit must be 10, got {len(page1)}"
    assert meta1["limit"] == 10
    assert meta1["offset"] == 0
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_route_stores(route["id"], territory_manager_headers, params={"offset": 10})
    )
    assert len(page2) == 2, f"offset=10 page must hold the remaining 2, got {len(page2)}"
    assert meta2["has_more"] is False
    assert meta2["total_count"] == 12
    assert page1[9]["id"] != page2[0]["id"], "pages must not overlap"
    assert {s["id"] for s in page1 + page2} == set(store_ids)


def test_reverse_reachability_filtered_lists(api, territory_manager_headers):
    """PRD §4: orders are covered by "List orders filtered by store, trip, or
    fulfillment status", invoices by "List invoices filtered by order, store,
    or status", returns by "List returns filtered by order, store, pickup trip,
    product, or status", credit memos by "List credit memos filtered by return,
    store, invoice, or status", trips by "List trips filtered by route, driver,
    or service date", sessions by "List sessions filtered by trip, store,
    driver, or status", readings by "List readings of a trip, recorded_at
    ascending", and crate events by "List crate transactions of a store".

    Design: Corner/endpoints/reverse_reachability_filtered_lists
    """
    refs = setup_delivered_order(prefix="DB", quantity_units=4)
    d_id = refs["distributor"]["id"]
    s1 = refs["store"]["id"]
    t1 = refs["trip"]["id"]
    dr1 = refs["driver"]["id"]
    o1 = refs["order"]["id"]
    inv1 = refs["invoice"]["id"]
    pl = refs["product"]["id"]

    ret = create_return(o1, s1, t1, pl, 1, "DAMAGED", "2026-09-01", dr1)
    approve_return(ret["id"], d_id)
    session_resp = api.check_in_merchandising_session(
        t1, {"store_id": s1}, make_driver_headers(dr1)
    )
    ms1 = validate_success(session_resp, 201)

    def only(items):
        assert len(items) == 1, f"expected exactly one match, got {len(items)}"
        return items[0]

    o_by_store, _ = validate_paginated(api.list_orders(territory_manager_headers, params={"store_id": s1}))
    o_by_trip, _ = validate_paginated(api.list_orders(territory_manager_headers, params={"trip_id": t1}))
    assert only(o_by_store)["id"] == o1 and only(o_by_trip)["id"] == o1

    inv_by_order, _ = validate_paginated(api.list_invoices(territory_manager_headers, params={"order_id": o1}))
    inv_by_store, _ = validate_paginated(api.list_invoices(territory_manager_headers, params={"store_id": s1}))
    assert only(inv_by_order)["id"] == inv1 and only(inv_by_store)["id"] == inv1

    r_by_trip, _ = validate_paginated(api.list_returns(territory_manager_headers, params={"pickup_trip_id": t1}))
    r_by_order, _ = validate_paginated(api.list_returns(territory_manager_headers, params={"order_id": o1}))
    assert only(r_by_trip)["id"] == ret["id"] and only(r_by_order)["id"] == ret["id"]

    m_by_inv, _ = validate_paginated(api.list_credit_memos(territory_manager_headers, params={"invoice_id": inv1}))
    m_by_ret, _ = validate_paginated(api.list_credit_memos(territory_manager_headers, params={"return_id": ret["id"]}))
    assert only(m_by_inv)["id"] == only(m_by_ret)["id"]

    t_by_driver, _ = validate_paginated(api.list_trips(territory_manager_headers, params={"driver_id": dr1}))
    assert only(t_by_driver)["id"] == t1

    s_by_trip, _ = validate_paginated(api.list_merchandising_sessions(territory_manager_headers, params={"trip_id": t1}))
    assert only(s_by_trip)["id"] == ms1["id"]

    readings, _ = validate_paginated(api.list_temperature_readings(t1, territory_manager_headers))
    assert readings[0]["temp_tenths_f"] == 380 and readings[0]["zone"] == "BOX"

    crates, _ = validate_paginated(api.list_crate_transactions(s1, territory_manager_headers))
    drop = only(crates)
    assert drop["kind"] == "DROP" and drop["crate_count"] == 4
