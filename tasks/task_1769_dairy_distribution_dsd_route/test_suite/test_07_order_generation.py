"""Standing-par order generation: weekday selection, defaults, idempotent
re-run, and input-set filtering (PRD §3.2)."""
from test_helpers import (
    TEST_USERS,
    create_driver,
    create_product,
    create_store,
    create_trip,
    get_store,
    make_distributor_owner_headers,
    set_clock,
    setup_route_with_store,
    upsert_par,
    validate_paginated,
    validate_success,
)

TM = TEST_USERS["territory_manager_headers"]


def test_generate_orders_from_par_and_idempotent(api, territory_manager_headers):
    """PRD §3.2: "Otherwise the system creates an order with `source` =
    `PAR_GENERATED`, `fulfillment_status` = `PLANNED`, `payment_status` =
    `UNINVOICED`, and a delivery window built from the service date plus the
    store's default `dock_open_min` and `dock_close_min`"
    PRD §3.2: "A store that already has an order on this trip in any
    `fulfillment_status` except `CANCELLED` is skipped the same way, which
    makes re-running generation idempotent."

    Design: Corner/calculations/generate_orders_from_par_and_idempotent
    """
    set_clock("2026-08-01T00:00:00Z")
    refs = setup_route_with_store(prefix="BE")
    d_id = refs["distributor"]["id"]
    store2 = create_store(refs["route"]["id"], d_id, store_code="S-BE-2")
    product = create_product("GEN-1", list_price_cents=250, shelf_life_days=30)
    upsert_par(
        refs["store"]["id"], d_id, product["id"],
        refs["store"]["version"], par_mon=10,
    )
    driver = create_driver(d_id, name="Sid Driver")
    trip = create_trip(refs["route"]["id"], driver["id"], d_id, service_date="2026-08-10")
    owner = make_distributor_owner_headers(d_id)

    first = validate_success(api.generate_orders(trip["id"], owner), 200)
    assert first["created_count"] == 1, "only S1 has a nonzero ACTIVE par"

    orders, _ = validate_paginated(
        api.list_orders(territory_manager_headers, params={"trip_id": trip["id"]})
    )
    assert len(orders) == 1
    gen = orders[0]
    assert gen["source"] == "PAR_GENERATED"
    assert gen["fulfillment_status"] == "PLANNED"
    assert gen["payment_status"] == "UNINVOICED"
    assert gen["store_id"] == refs["store"]["id"]
    assert gen["delivery_window_start"] == "2026-08-10T08:00:00Z", (
        "dock default 480 minutes after midnight on the service date"
    )
    assert gen["delivery_window_end"] == "2026-08-10T12:00:00Z", (
        "dock default 720 minutes after midnight on the service date"
    )
    assert gen["lines"] == [{"product_id": product["id"], "quantity_units": 10}]

    second = validate_success(api.generate_orders(trip["id"], owner), 200)
    assert second["created_count"] == 0, "idempotent re-run creates nothing"
    assert refs["store"]["id"] in second["skipped_store_ids"]


def test_generate_orders_excludes_discontinued_and_zero_par(api, territory_manager_headers):
    """PRD §3.2: "For each store, the generated lines come from that store's
    `ACTIVE` pars: a line `{product_id, quantity_units}` is included when the
    par quantity for the service date's weekday is greater than zero and the
    product is `ACTIVE`; `DISCONTINUED` products are silently excluded. A
    store with no qualifying lines is skipped and recorded in the response's
    `skipped_store_ids`."

    Design: Corner/calculations/generate_orders_excludes_discontinued_and_zero_par
    """
    set_clock("2026-08-01T00:00:00Z")
    refs = setup_route_with_store(prefix="BF")
    d_id = refs["distributor"]["id"]
    store2 = create_store(refs["route"]["id"], d_id, store_code="S-BF-2")
    pa = create_product("GEN-2", list_price_cents=250, shelf_life_days=30)
    pb = create_product("GEN-3", list_price_cents=250, shelf_life_days=30)

    upsert_par(refs["store"]["id"], d_id, pa["id"], refs["store"]["version"], par_mon=10)
    v = get_store(refs["store"]["id"])["version"]
    upsert_par(refs["store"]["id"], d_id, pb["id"], v, par_mon=6)
    upsert_par(store2["id"], d_id, pa["id"], store2["version"], par_mon=0)

    api.discontinue_product(pb["id"], TM)

    driver = create_driver(d_id, name="Tad Driver")
    trip = create_trip(refs["route"]["id"], driver["id"], d_id, service_date="2026-08-10")
    owner = make_distributor_owner_headers(d_id)

    result = validate_success(api.generate_orders(trip["id"], owner), 200)
    assert result["created_count"] == 1
    assert store2["id"] in result["skipped_store_ids"], (
        "a par whose Monday quantity is 0 produces no line, so S2 is skipped"
    )

    orders, _ = validate_paginated(
        api.list_orders(territory_manager_headers, params={"trip_id": trip["id"]})
    )
    assert len(orders) == 1
    assert orders[0]["lines"] == [{"product_id": pa["id"], "quantity_units": 10}], (
        "the DISCONTINUED product's par contributes no line"
    )
