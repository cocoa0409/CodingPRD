"""Corner queue B — Section 4: validations (auth header, RBAC, OCC, FK integrity)."""

from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    make_driver_headers,
    create_customer_payload,
    create_tank_site_payload,
    create_tank_payload,
    create_driver_payload,
    create_route_payload,
    create_route_stop_payload,
    create_settle_payload,
    create_active_customer_with_installed_tank,
    create_customer,
    create_driver,
    create_route,
    add_stop_to_route,
    publish_price,
    setup_completed_pickup,
)


def test_missing_user_context_header_returns_400(api):
    """PRD §2.1: "A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)".

    Design: Corner/validations/missing_user_context_header_returns_400
    """
    # Manually craft headers with role missing
    resp = api_client._request("GET", "/recycle-routes/customers", headers={"X-User-ID": "u1"})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_insufficient_permissions_driver_cannot_settle(api):
    """PRD §2.1: "When the named role is not permitted to invoke the endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)" and §4 assigns settle to SettlementClerk only.

    Design: Corner/validations/insufficient_permissions_driver_cannot_settle
    """
    ctx = setup_completed_pickup(route_eligibility_override=True, route_code="RBAC")
    cust_now = get_success_data(api_client.get_customer(ctx["customer"]["id"], TEST_USERS["settlement_clerk_headers"]))
    drv = make_driver_headers(ctx["driver"]["id"])
    resp = api_client.settle_pickup_ticket(
        ctx["ticket"]["id"],
        create_settle_payload(cust_now["version"]),
        drv,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_planner_cannot_record_screening(api):
    """PRD §3.4: "A `LabTech` — never the driver — records the sample screening" and §4 assigns POST /route-stops/{id}/sample-screenings to LabTech.

    Design: Corner/validations/planner_cannot_record_screening
    """
    base = create_active_customer_with_installed_tank(intake_gallons=100)
    driver = create_driver()
    publish_price()
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="RBAC2")
    stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    stop = get_success_data(api_client.arrive_route_stop(stop["id"], drv))
    stop = get_success_data(api_client.begin_screening_route_stop(stop["id"], drv))
    # Planner attempts to record screening → denied
    resp = api_client.create_sample_screening(
        stop["id"],
        {"halogen_ppm": 10, "water_pct": 1.0, "ph_level": 7.0},
        TEST_USERS["route_planner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_route_stop_create_with_stale_route_version(api):
    """PRD §2.7: "Adding a stop to a route requires the request body to carry `expected_route_version`... a writer whose view of the route's capacity and sequence allocation is stale... is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/validations/route_stop_create_with_stale_route_version
    """
    base = create_active_customer_with_installed_tank()
    driver = create_driver()
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="OCC1")
    stale_version = route["version"]  # capture v1
    # First stop succeeds; bumps route version
    add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], stale_version)
    # Second stop uses stale version
    resp = api_client.create_route_stop(
        route["id"],
        create_route_stop_payload(
            base["site"]["id"], base["tank"]["id"], stale_version,
            scheduled_window_start="10:00", scheduled_window_end="11:00",
            sequence=2, estimated_volume_gallons=50,
        ),
        TEST_USERS["route_planner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_ticket_settle_with_stale_customer_version(api):
    """PRD §2.7: "Settling a pickup ticket requires the request body to carry `expected_customer_version`, the customer `version` the clerk last observed... the mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/validations/ticket_settle_with_stale_customer_version
    """
    ctx = setup_completed_pickup(
        credit_terms="PREPAY", route_eligibility_override=True, route_code="OCC2",
    )
    # Clerk captures customer version BEFORE top-up
    cust_pre = get_success_data(api_client.get_customer(ctx["customer"]["id"], TEST_USERS["settlement_clerk_headers"]))
    stale_cv = cust_pre["version"]
    # Top-up increments customer version
    get_success_data(api_client.top_up_customer(
        ctx["customer"]["id"], {"amount_cents": 1000}, TEST_USERS["settlement_clerk_headers"],
    ))
    resp = api_client.settle_pickup_ticket(
        ctx["ticket"]["id"],
        create_settle_payload(stale_cv),
        TEST_USERS["settlement_clerk_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_fk_integrity_route_stop_with_bad_tank_id(api):
    """PRD §2.5: "Foreign-key references carried in a request body... must likewise resolve to existing resources, and an unresolvable reference is rejected with the referenced resource's not-found error".

    Design: Corner/validations/fk_integrity_route_stop_with_bad_tank_id
    """
    cust = create_customer(legal_name="FK", epa_generator_id="EPAGEN000144")
    site = get_success_data(api_client.create_tank_site(
        create_tank_site_payload(cust["id"]), TEST_USERS["route_planner_headers"],
    ))
    driver = create_driver()
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="FK")
    resp = api_client.create_route_stop(
        route["id"],
        create_route_stop_payload(site["id"], NON_EXISTENT_UUID, route["version"]),
        TEST_USERS["route_planner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_TANK_NOT_FOUND)
