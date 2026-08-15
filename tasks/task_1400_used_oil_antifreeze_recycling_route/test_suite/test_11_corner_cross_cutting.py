"""Corner queue B — Section 8: cross-cutting complexity layers (cascades, derived fields, idempotency)."""

from test_helpers import (
    api_client,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_driver_headers,
    create_route_payload,
    create_route_stop_payload,
    create_sample_screening_payload,
    create_pickup_ticket_payload,
    create_active_customer_with_installed_tank,
    create_driver,
    create_route,
    add_stop_to_route,
    publish_price,
)


def test_cascading_side_effects_customer_suspend(api):
    """PRD §3.1: "Suspension (`ACTIVE` → `SUSPENDED`) requires an `ACTIVE` customer (otherwise `ERR_CUSTOMER_NOT_ACTIVE`) and cascades: every tank site under the customer becomes `INACTIVE`, and every future-dated stop still `SCHEDULED` against any tank at those sites becomes `CANCELLED_CUSTOMER`."

    Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_customer_suspend
    """
    base = create_active_customer_with_installed_tank(tank_kind="USED_OIL", capacity_gallons=100)
    driver = create_driver()
    # Future-dated route
    route = create_route(driver["id"], scheduled_date="2026-08-15", route_code="CASC")
    stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    # Suspend customer
    get_success_data(api_client.suspend_customer(base["customer"]["id"], TEST_USERS["route_planner_headers"]))
    site_after = get_success_data(api_client.get_tank_site(base["site"]["id"], TEST_USERS["route_planner_headers"]))
    stop_after = get_success_data(api_client.get_route_stop(stop["id"], TEST_USERS["route_planner_headers"]))
    assert site_after["status"] == "INACTIVE"
    assert stop_after["status"] == "CANCELLED_CUSTOMER"


def test_derived_field_route_loaded_gallons(api):
    """PRD §2.9: "A route's `loaded_gallons` accumulates metered volume from completed stops".

    Design: Corner/cross_cutting_complexity_layers/derived_field_route_loaded_gallons
    """
    base = create_active_customer_with_installed_tank(
        route_eligibility_override=True, intake_gallons=300,
    )
    driver = create_driver()
    publish_price(price_cents_per_gal=50)
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="DER",
                         vehicle_capacity_gallons=500)
    stop1 = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"],
                              scheduled_window_start="08:00", scheduled_window_end="09:00", sequence=1,
                              estimated_volume_gallons=60)
    route = get_success_data(api_client.get_route(route["id"], TEST_USERS["route_planner_headers"]))
    stop2 = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"],
                              scheduled_window_start="10:00", scheduled_window_end="11:00", sequence=2,
                              estimated_volume_gallons=40)
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    # Stop 1: 60 gal
    stop1 = get_success_data(api_client.arrive_route_stop(stop1["id"], drv))
    stop1 = get_success_data(api_client.begin_screening_route_stop(stop1["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop1["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
    ))
    get_success_data(api_client.create_pickup_ticket(
        stop1["id"], create_pickup_ticket_payload(client_request_id="DER-1", metered_volume_gallons=60), drv,
    ))
    route_mid = get_success_data(api_client.get_route(route["id"], TEST_USERS["route_planner_headers"]))
    assert route_mid["loaded_gallons"] == 60
    # Stop 2: 40 gal
    stop2 = get_success_data(api_client.arrive_route_stop(stop2["id"], drv))
    stop2 = get_success_data(api_client.begin_screening_route_stop(stop2["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop2["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
    ))
    get_success_data(api_client.create_pickup_ticket(
        stop2["id"], create_pickup_ticket_payload(client_request_id="DER-2", metered_volume_gallons=40), drv,
    ))
    route_final = get_success_data(api_client.get_route(route["id"], TEST_USERS["route_planner_headers"]))
    assert route_final["loaded_gallons"] == 100
