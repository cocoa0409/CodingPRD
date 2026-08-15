"""Corner queue B — Section 9: consistency model (immediate) and clock default."""

from test_helpers import (
    api_client,
    get_success_data,
    TEST_USERS,
    make_driver_headers,
    create_pickup_ticket_payload,
    setup_ready_to_pump_stop,
)


def test_pickup_immediately_visible_in_route_and_tank(api):
    """PRD §2.9: "All mutations commit immediately within a single request; there is no asynchronous processing."

    Design: Corner/consistency_model/pickup_immediately_visible_in_route_and_tank
    """
    ctx = setup_ready_to_pump_stop(
        route_eligibility_override=True, intake_gallons=100, route_code="CONS",
    )
    drv = make_driver_headers(ctx["driver"]["id"])
    get_success_data(api_client.create_pickup_ticket(
        ctx["stop"]["id"],
        create_pickup_ticket_payload(client_request_id="CONS-PT", metered_volume_gallons=100),
        drv,
    ))
    route_after = get_success_data(api_client.get_route(ctx["route"]["id"], TEST_USERS["route_planner_headers"]))
    tank_after = get_success_data(api_client.get_tank(ctx["tank"]["id"], TEST_USERS["ehs_officer_headers"]))
    assert route_after["loaded_gallons"] == 100
    assert tank_after["current_volume_gallons"] == 0


def test_imate_clock_default_is_2026_08_01(api):
    """PRD §2.10: "At startup, before any clock-setting call, the logical clock reads exactly `2026-08-01T00:00:00Z`" and PRD §3.5: "a row dated exactly the scheduled date is used".

    Design: Corner/consistency_model/imate_clock_default_is_2026_08_01
    """
    # Route scheduled on the default clock date; price effective same date — inclusive boundary
    ctx = setup_ready_to_pump_stop(
        route_eligibility_override=True, intake_gallons=100,
        scheduled_date="2026-08-01", route_code="CLK", price_cents_per_gal=50,
    )
    drv = make_driver_headers(ctx["driver"]["id"])
    ticket = get_success_data(api_client.create_pickup_ticket(
        ctx["stop"]["id"],
        create_pickup_ticket_payload(client_request_id="CLK-PT", metered_volume_gallons=100),
        drv,
    ))
    assert ticket["commodity_price_cents_per_gal"] == 50
