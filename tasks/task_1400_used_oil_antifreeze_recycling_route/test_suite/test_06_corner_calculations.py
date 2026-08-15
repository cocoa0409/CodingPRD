"""Corner queue B — Section 3: calculations (surcharge tiers, market price lookup)."""

from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_driver_headers,
    create_route_payload,
    create_route_stop_payload,
    create_sample_screening_payload,
    create_pickup_ticket_payload,
    create_market_price_payload,
    create_active_customer_with_installed_tank,
    create_driver,
    create_route,
    add_stop_to_route,
    publish_price,
    drive_halogen_violations,
    setup_completed_pickup,
    setup_ready_to_pump_stop,
)


def test_halogen_surcharge_tier_0(api):
    """PRD §3.5: "zero violations means no surcharge".

    Design: Corner/calculations/halogen_surcharge_tier_0
    """
    ctx = setup_completed_pickup(
        price_cents_per_gal=50, metered_volume_gallons=100,
        intake_gallons=100, route_eligibility_override=True, route_code="T0",
    )
    ticket = ctx["ticket"]
    assert ticket["surcharge_cents"] == 0
    assert ticket["net_amount_cents"] == 5000  # 50*100 - 0 - 0


def test_halogen_surcharge_tier_1(api):
    """PRD §3.5: "one or two violations assess a flat 500 cents (five dollars)".

    Design: Corner/calculations/halogen_surcharge_tier_1
    """
    base = create_active_customer_with_installed_tank(
        tank_kind="USED_OIL", capacity_gallons=1000,
        route_eligibility_override=True, intake_gallons=500,
    )
    driver = create_driver()
    publish_price(price_cents_per_gal=50)
    drive_halogen_violations(base["customer"], base["site"], base["tank"], driver, 2, route_code_prefix="T1")
    # Final PASS pickup
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="T1-C",
                         vehicle_capacity_gallons=500)
    stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    stop = get_success_data(api_client.arrive_route_stop(stop["id"], drv))
    stop = get_success_data(api_client.begin_screening_route_stop(stop["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
    ))
    ticket = get_success_data(api_client.create_pickup_ticket(
        stop["id"], create_pickup_ticket_payload(client_request_id="T1-PT", metered_volume_gallons=100), drv,
    ))
    assert ticket["surcharge_cents"] == 500
    assert ticket["net_amount_cents"] == 4500  # 5000 - 500 - 0


def test_market_price_backward_looking(api):
    """PRD §3.5: "the server selects, among the rows for the customer's `market_zone` and the tank's `tank_kind`, the most recent row whose `effective_date` is on or before the route's `scheduled_date`... and never uses a future-dated row."

    Design: Corner/calculations/market_price_backward_looking
    """
    base = create_active_customer_with_installed_tank(
        route_eligibility_override=True, intake_gallons=100,
    )
    driver = create_driver()
    publish_price(market_zone="NORTH", tank_kind="USED_OIL", effective_date="2026-08-01",
                  price_cents_per_gal=50)
    publish_price(market_zone="NORTH", tank_kind="USED_OIL", effective_date="2026-08-10",
                  price_cents_per_gal=99)
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="BAK",
                         vehicle_capacity_gallons=500)
    stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    stop = get_success_data(api_client.arrive_route_stop(stop["id"], drv))
    stop = get_success_data(api_client.begin_screening_route_stop(stop["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
    ))
    ticket = get_success_data(api_client.create_pickup_ticket(
        stop["id"], create_pickup_ticket_payload(client_request_id="BAK-PT", metered_volume_gallons=100), drv,
    ))
    assert ticket["commodity_price_cents_per_gal"] == 50


def test_market_price_missing_returns_err(api):
    """PRD §3.5: "If no such row exists, the pickup is rejected with `ERR_PRICE_NOT_PUBLISHED` (HTTP 422)".

    Design: Corner/calculations/market_price_missing_returns_err
    """
    # Customer in COASTAL zone; only NORTH prices published → no match for (COASTAL, USED_OIL)
    base = create_active_customer_with_installed_tank(
        market_zone="COASTAL", route_eligibility_override=True, intake_gallons=100,
    )
    driver = create_driver()
    # Publish a NORTH price only — COASTAL has no match
    publish_price(market_zone="NORTH", tank_kind="USED_OIL", effective_date="2026-08-01",
                  price_cents_per_gal=50)
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="NOPX",
                         vehicle_capacity_gallons=500)
    stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    stop = get_success_data(api_client.arrive_route_stop(stop["id"], drv))
    stop = get_success_data(api_client.begin_screening_route_stop(stop["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
    ))
    resp = api_client.create_pickup_ticket(
        stop["id"],
        create_pickup_ticket_payload(client_request_id="NOPX-PT", metered_volume_gallons=100),
        drv,
    )
    validate_error(resp, ApiErrorId.ERR_PRICE_NOT_PUBLISHED)
