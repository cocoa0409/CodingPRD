"""Corner queue B — Section 7: RBAC (per-role allow/deny)."""

from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_driver_headers,
    create_spill_incident_payload,
    create_active_customer_with_installed_tank,
    create_driver,
    create_route,
    add_stop_to_route,
    publish_price,
    setup_manifest_delivered,
)


def test_ehs_officer_can_certify_clean_but_planner_cannot(api):
    """PRD §3.9: "Only once every spill at a site has reached `REMEDIATED`, `CLOSED_NO_ACTION`, or `CLOSED_WITH_LIABILITY` may an `EHSOfficer` certify the site clean" and §4 assigns certify-clean to EHSOfficer only.

    Design: Corner/rbac/ehs_officer_can_certify_clean_but_planner_cannot
    """
    base = create_active_customer_with_installed_tank(tank_kind="USED_OIL", capacity_gallons=100)
    driver = create_driver()
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="EHS")
    drv = make_driver_headers(driver["id"])
    # Reportable spill → site CONTAMINATED
    spill = get_success_data(api_client.create_spill_incident(
        create_spill_incident_payload(route["id"], base["site"]["id"], gallons_spilled=30, cause_code="CUSTOMER_OVERFILL"),
        drv,
    ))
    api_client.begin_investigation_spill(spill["id"], TEST_USERS["ehs_officer_headers"])
    api_client.remediate_spill(spill["id"], TEST_USERS["ehs_officer_headers"])
    api_client.close_spill(spill["id"], TEST_USERS["ehs_officer_headers"])
    # Planner denied
    resp = api_client.certify_clean_tank_site(base["site"]["id"], TEST_USERS["route_planner_headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    # EHSOfficer succeeds
    site = get_success_data(api_client.certify_clean_tank_site(base["site"]["id"], TEST_USERS["ehs_officer_headers"]))
    assert site["status"] == "ACTIVE"


def test_lab_tech_cannot_dispatch_route(api):
    """PRD §2.1: "When the named role is not permitted to invoke the endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)" and §4 assigns dispatch to RoutePlanner only.

    Design: Corner/rbac/lab_tech_cannot_dispatch_route
    """
    base = create_active_customer_with_installed_tank(tank_kind="USED_OIL", capacity_gallons=100)
    driver = create_driver()
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="LAB")
    add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    resp = api_client.dispatch_route(route["id"], TEST_USERS["lab_tech_headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_regulator_can_close_manifest_but_driver_cannot(api):
    """PRD §3.7: "Closure is the regulator's act" and §4 assigns manifest close to Regulator only.

    Design: Corner/rbac/regulator_can_close_manifest_but_driver_cannot
    """
    ctx = setup_manifest_delivered(manifest_tracking_number="MAN-RBAC", facility_epa_id="EPAID-RBAC")
    drv = make_driver_headers(ctx["driver"]["id"])
    # Driver denied
    resp = api_client.close_manifest(ctx["manifest"]["id"], drv)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    # Regulator succeeds
    manifest = get_success_data(api_client.close_manifest(ctx["manifest"]["id"], TEST_USERS["regulator_headers"]))
    assert manifest["status"] == "CLOSED"
