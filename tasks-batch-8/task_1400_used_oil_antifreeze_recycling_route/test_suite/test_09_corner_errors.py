"""Corner queue B — Section 6: errors (every error code triggerable)."""

from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    make_driver_headers,
    create_settle_payload,
    create_spill_incident_payload,
    create_active_customer_with_installed_tank,
    create_customer,
    create_driver,
    create_route,
    setup_completed_pickup,
)


def test_error_manifest_not_found(api):
    """PRD §2.5: "The per-resource not-found identifiers are: ... `ERR_MANIFEST_NOT_FOUND`... (all HTTP 404)".

    Design: Corner/errors/error_manifest_not_found
    """
    resp = api_client.get_manifest(NON_EXISTENT_UUID, TEST_USERS["route_planner_headers"])
    validate_error(resp, ApiErrorId.ERR_MANIFEST_NOT_FOUND)


def test_error_route_not_found(api):
    """PRD §2.5: "The per-resource not-found identifiers are: ... `ERR_ROUTE_NOT_FOUND`... (all HTTP 404)".

    Design: Corner/errors/error_route_not_found
    """
    resp = api_client.get_route(NON_EXISTENT_UUID, TEST_USERS["route_planner_headers"])
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_FOUND)


def test_error_stop_not_scheduled_on_arrive_after_completed(api):
    """PRD §3.4: "Arrival requires the stop to be `SCHEDULED` (otherwise `ERR_STOP_NOT_SCHEDULED`)".

    Design: Corner/errors/error_stop_not_scheduled_on_arrive_after_completed
    """
    ctx = setup_completed_pickup(route_eligibility_override=True, route_code="TERM", intake_gallons=200)
    drv = make_driver_headers(ctx["driver"]["id"])
    # Stop is now COMPLETED — arrive is invalid
    resp = api_client.arrive_route_stop(ctx["stop"]["id"], drv)
    validate_error(resp, ApiErrorId.ERR_STOP_NOT_SCHEDULED)


def test_error_prepay_insufficient_balance_on_settle(api):
    """PRD §3.6: "For a `PREPAY` customer whose ticket net is negative, settlement additionally requires the prepaid balance to absorb the charge — `prepaid_balance_cents` plus the negative `net_amount_cents` must not drop below zero — otherwise the settle is rejected with `ERR_INSUFFICIENT_PREPAID_BALANCE` (HTTP 402)".

    Design: Corner/errors/error_prepay_insufficient_balance_on_settle
    """
    # PREPAY customer, prepaid=0, negative-price pickup → net negative charge
    ctx = setup_completed_pickup(
        market_zone="SOUTH", credit_terms="PREPAY", tank_kind="ANTIFREEZE",
        price_cents_per_gal=-50, metered_volume_gallons=100, intake_gallons=100,
        route_eligibility_override=True, route_code="PREB",
    )
    assert ctx["ticket"]["net_amount_cents"] == -5000
    assert ctx["customer"]["prepaid_balance_cents"] == 0
    cust_now = get_success_data(api_client.get_customer(ctx["customer"]["id"], TEST_USERS["settlement_clerk_headers"]))
    resp = api_client.settle_pickup_ticket(
        ctx["ticket"]["id"],
        create_settle_payload(cust_now["version"]),
        TEST_USERS["settlement_clerk_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PREPAID_BALANCE)


def test_error_customer_terminate_with_outstanding_balance(api):
    """PRD §3.1: "Termination (`ACTIVE` → `TERMINATED`, the terminal state) requires ... zero `outstanding_charge_cents` (`ERR_OUTSTANDING_BALANCE`)".

    Design: Corner/errors/error_customer_terminate_with_outstanding_balance
    """
    # Create customer with liability outstanding via a spill (SHARED UNKNOWN at 7 gal → 2975 outstanding)
    base = create_active_customer_with_installed_tank(tank_kind="USED_OIL", capacity_gallons=100)
    driver = create_driver()
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="TERM-OUT")
    drv = make_driver_headers(driver["id"])
    spill = get_success_data(api_client.create_spill_incident(
        create_spill_incident_payload(route["id"], base["site"]["id"], gallons_spilled=7, cause_code="UNKNOWN"),
        drv,
    ))
    api_client.begin_investigation_spill(spill["id"], TEST_USERS["ehs_officer_headers"])
    api_client.remediate_spill(spill["id"], TEST_USERS["ehs_officer_headers"])
    api_client.close_spill(spill["id"], TEST_USERS["ehs_officer_headers"])
    # Customer now has outstanding_charge_cents = 2975
    resp = api_client.terminate_customer(base["customer"]["id"], TEST_USERS["route_planner_headers"])
    validate_error(resp, ApiErrorId.ERR_OUTSTANDING_BALANCE)
