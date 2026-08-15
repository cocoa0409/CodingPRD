"""Composite setup helpers — multi-step API call chains that build PRD state.

Every fixture uses `get_success_data()` so setup failures surface as clear
"Setup failed" errors rather than assertion errors deep in the chain.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_customer_payload,
    create_tank_site_payload,
    create_tank_payload,
    create_driver_payload,
    create_route_payload,
    create_route_stop_payload,
    create_sample_screening_payload,
    create_pickup_ticket_payload,
    create_disposal_facility_payload,
    create_manifest_payload,
    create_blend_batch_payload,
    create_spill_incident_payload,
    create_market_price_payload,
    create_settle_payload,
)
from .test_users import TEST_USERS, make_driver_headers


# ---------- Tier 1: single-entity state progression ----------

def create_customer(**overrides):
    """Create a customer (PROSPECT). Returns Customer dict."""
    payload = create_customer_payload(**overrides)
    resp = api_client.create_customer(payload, TEST_USERS["route_planner_headers"])
    return get_success_data(resp)


def create_active_customer_with_installed_tank(
    market_zone="NORTH",
    credit_terms="NET30",
    density_zone="URBAN",
    tank_kind="USED_OIL",
    capacity_gallons=500,
    ownership="CUSTOMER_OWNED",
    route_eligibility_override=False,
    intake_gallons=0,
    legal_name="FixCust",
):
    """Create customer + site + tank + install + (optional intake) + activate.

    Returns dict with keys: customer, site, tank, driver=None.
    """
    cust = create_customer(legal_name=legal_name, market_zone=market_zone, credit_terms=credit_terms)
    site_payload = create_tank_site_payload(cust["id"], density_zone=density_zone)
    if route_eligibility_override:
        site_payload["route_eligibility_override"] = True
    site = get_success_data(api_client.create_tank_site(site_payload, TEST_USERS["route_planner_headers"]))
    tank = get_success_data(api_client.create_tank(
        create_tank_payload(site["id"], tank_kind=tank_kind, capacity_gallons=capacity_gallons, ownership=ownership),
        TEST_USERS["tank_installer_headers"],
    ))
    # Install / register-existing per ownership
    if ownership == "COMPANY_OWNED":
        tank = get_success_data(api_client.install_tank(tank["id"], TEST_USERS["tank_installer_headers"]))
    else:
        tank = get_success_data(api_client.register_existing_tank(tank["id"], TEST_USERS["tank_installer_headers"]))
    if intake_gallons:
        tank = get_success_data(api_client.record_intake(
            tank["id"], {"gallons": intake_gallons}, TEST_USERS["route_planner_headers"],
        ))
    cust = get_success_data(api_client.activate_customer(cust["id"], TEST_USERS["route_planner_headers"]))
    return {"customer": cust, "site": site, "tank": tank}


def create_driver(**overrides):
    """Create a driver (ACTIVE). Returns Driver dict."""
    resp = api_client.create_driver(create_driver_payload(**overrides), TEST_USERS["route_planner_headers"])
    return get_success_data(resp)


def create_route(driver_id, **overrides):
    """Create a route (PLANNED). Returns Route dict."""
    resp = api_client.create_route(create_route_payload(driver_id, **overrides), TEST_USERS["route_planner_headers"])
    return get_success_data(resp)


def add_stop_to_route(route_id, tank_site_id, tank_id, expected_route_version, **overrides):
    """Add a stop to a route. Returns RouteStop dict."""
    payload = create_route_stop_payload(tank_site_id, tank_id, expected_route_version, **overrides)
    resp = api_client.create_route_stop(route_id, payload, TEST_USERS["route_planner_headers"])
    return get_success_data(resp)


def publish_price(**overrides):
    """Publish a MarketPrice row. Returns MarketPrice dict."""
    resp = api_client.create_market_price(create_market_price_payload(**overrides), TEST_USERS["regulator_headers"])
    return get_success_data(resp)


def create_disposal_facility(**overrides):
    """Create a DisposalFacility (ACTIVE)."""
    resp = api_client.create_disposal_facility(create_disposal_facility_payload(**overrides), TEST_USERS["regulator_headers"])
    return get_success_data(resp)


# ---------- Tier 2/3: composite setup ----------

def setup_ready_to_pump_stop(
    market_zone="NORTH",
    credit_terms="NET30",
    density_zone="URBAN",
    tank_kind="USED_OIL",
    capacity_gallons=500,
    intake_gallons=200,
    price_cents_per_gal=50,
    route_eligibility_override=False,
    scheduled_date="2026-08-05",
    route_code="FX-1",
    vehicle_capacity_gallons=500,
    legal_name="FxCust",
    manifest_facility_id=None,
    manifest_tracking_number=None,
):
    """Drive a stop all the way to READY_TO_PUMP.

    Returns dict with keys: customer, site, tank, driver, route, stop, screening.
    If manifest_facility_id is provided, also creates a manifest and includes 'manifest'.
    PRD §3.7 requires manifest_tracking_number to be unique, so the default is
    unique per call.
    """
    base = create_active_customer_with_installed_tank(
        market_zone=market_zone,
        credit_terms=credit_terms,
        density_zone=density_zone,
        tank_kind=tank_kind,
        capacity_gallons=capacity_gallons,
        route_eligibility_override=route_eligibility_override,
        intake_gallons=intake_gallons,
        legal_name=legal_name,
    )
    driver = create_driver()
    publish_price(market_zone=market_zone, tank_kind=tank_kind, effective_date="2026-08-01",
                  price_cents_per_gal=price_cents_per_gal)
    route = create_route(driver["id"], scheduled_date=scheduled_date, route_code=route_code,
                         vehicle_capacity_gallons=vehicle_capacity_gallons, density_zone=density_zone)
    stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    manifest = None
    if manifest_facility_id is not None:
        if manifest_tracking_number is None:
            manifest_tracking_number = f"MAN-{uuid.uuid4().hex[:12]}"
        manifest = get_success_data(api_client.create_manifest(
            route["id"],
            create_manifest_payload(manifest_facility_id, manifest_tracking_number=manifest_tracking_number),
            TEST_USERS["route_planner_headers"],
        ))
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    drv_headers = make_driver_headers(driver["id"])
    stop = get_success_data(api_client.arrive_route_stop(stop["id"], drv_headers))
    stop = get_success_data(api_client.begin_screening_route_stop(stop["id"], drv_headers))
    screening = get_success_data(api_client.create_sample_screening(
        stop["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
    ))
    # After PASS, stop is READY_TO_PUMP
    stop = get_success_data(api_client.get_route_stop(stop["id"], drv_headers))
    out = {
        "customer": base["customer"],
        "site": base["site"],
        "tank": base["tank"],
        "driver": driver,
        "route": route,
        "stop": stop,
        "screening": screening,
    }
    if manifest is not None:
        out["manifest"] = manifest
    return out


def drive_halogen_violations(customer, site, tank, driver, count, route_code_prefix="HAL"):
    """Run `count` halogen-fail screenings on `tank` to drive customer.halogen_violation_count.

    Each iteration: route → stop → dispatch → arrive → begin-screening → halogen-fail screening
    → clear quarantine (EHS).
    """
    drv_headers = make_driver_headers(driver["id"])
    for i in range(count):
        route = create_route(
            driver["id"],
            scheduled_date=f"2026-08-0{(i + 2) % 9}",
            route_code=f"{route_code_prefix}-{i}",
            vehicle_capacity_gallons=2000,
            density_zone=site["density_zone"],
        )
        stop = add_stop_to_route(route["id"], site["id"], tank["id"], route["version"])
        route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
        stop = get_success_data(api_client.arrive_route_stop(stop["id"], drv_headers))
        stop = get_success_data(api_client.begin_screening_route_stop(stop["id"], drv_headers))
        get_success_data(api_client.create_sample_screening(
            stop["id"],
            create_sample_screening_payload(halogen_ppm=5000),
            TEST_USERS["lab_tech_headers"],
        ))
        # Tank now QUARANTINED; clear for next round
        get_success_data(api_client.clear_quarantine_tank(tank["id"], TEST_USERS["ehs_officer_headers"]))


def setup_completed_pickup(
    market_zone="NORTH",
    credit_terms="NET30",
    density_zone="URBAN",
    tank_kind="USED_OIL",
    capacity_gallons=500,
    intake_gallons=200,
    price_cents_per_gal=50,
    route_eligibility_override=False,
    scheduled_date="2026-08-05",
    route_code="PU-1",
    metered_volume_gallons=100,
    vehicle_capacity_gallons=500,
    client_request_id="PT-1",
    legal_name="PickCust",
    manifest_facility_id=None,
    manifest_tracking_number=None,
):
    """Drive a stop all the way to COMPLETED, producing a PROVISIONAL PickupTicket.

    Returns dict with keys: customer, site, tank, driver, route, stop, ticket (+ manifest if requested).
    """
    ctx = setup_ready_to_pump_stop(
        market_zone=market_zone,
        credit_terms=credit_terms,
        density_zone=density_zone,
        tank_kind=tank_kind,
        capacity_gallons=capacity_gallons,
        intake_gallons=intake_gallons,
        price_cents_per_gal=price_cents_per_gal,
        route_eligibility_override=route_eligibility_override,
        scheduled_date=scheduled_date,
        route_code=route_code,
        vehicle_capacity_gallons=vehicle_capacity_gallons,
        legal_name=legal_name,
        manifest_facility_id=manifest_facility_id,
        manifest_tracking_number=manifest_tracking_number,
    )
    drv_headers = make_driver_headers(ctx["driver"]["id"])
    ticket = get_success_data(api_client.create_pickup_ticket(
        ctx["stop"]["id"],
        create_pickup_ticket_payload(client_request_id=client_request_id, metered_volume_gallons=metered_volume_gallons),
        drv_headers,
    ))
    ctx["ticket"] = ticket
    # Refresh stop to COMPLETED
    ctx["stop"] = get_success_data(api_client.get_route_stop(ctx["stop"]["id"], drv_headers))
    return ctx


def setup_settled_ticket(
    expected_customer_version=None,
    **kwargs,
):
    """setup_completed_pickup + settle. Returns ctx with 'ticket' SETTLED and 'customer' refreshed."""
    ctx = setup_completed_pickup(**kwargs)
    if expected_customer_version is None:
        cust_now = get_success_data(api_client.get_customer(ctx["customer"]["id"], TEST_USERS["settlement_clerk_headers"]))
        expected_customer_version = cust_now["version"]
    ticket = get_success_data(api_client.settle_pickup_ticket(
        ctx["ticket"]["id"],
        create_settle_payload(expected_customer_version),
        TEST_USERS["settlement_clerk_headers"],
    ))
    ctx["ticket"] = ticket
    ctx["customer"] = get_success_data(api_client.get_customer(ctx["customer"]["id"], TEST_USERS["settlement_clerk_headers"]))
    return ctx


def setup_manifest_delivered(
    manifest_tracking_number="MAN-D1",
    price_cents_per_gal=50,
    metered_volume_gallons=100,
    facility_capacity=10000,
    accepted_streams=None,
    facility_epa_id="EPAID-MAN",
):
    """Build route COMPLETE with manifest DELIVERED. Returns ctx with manifest, route, etc."""
    if accepted_streams is None:
        accepted_streams = ["USED_OIL"]
    facility = create_disposal_facility(
        epa_id=facility_epa_id,
        accepted_streams=accepted_streams,
        daily_capacity_gallons=facility_capacity,
    )
    ctx = setup_completed_pickup(
        price_cents_per_gal=price_cents_per_gal,
        metered_volume_gallons=metered_volume_gallons,
        route_code="DELIV",
        route_eligibility_override=True,
        manifest_facility_id=facility["id"],
        manifest_tracking_number=manifest_tracking_number,
    )
    manifest = ctx["manifest"]
    manifest = get_success_data(api_client.submit_manifest(manifest["id"], TEST_USERS["route_planner_headers"]))
    route = get_success_data(api_client.complete_route(ctx["route"]["id"], TEST_USERS["route_planner_headers"]))
    drv_headers = make_driver_headers(ctx["driver"]["id"])
    manifest = get_success_data(api_client.depart_manifest(manifest["id"], drv_headers))
    manifest = get_success_data(api_client.deliver_manifest(manifest["id"], drv_headers))
    ctx["manifest"] = manifest
    ctx["route"] = route
    ctx["facility"] = facility
    return ctx


def setup_spill_remediated(
    gallons_spilled=7,
    cause_code="UNKNOWN",
    tank_ownership="CUSTOMER_OWNED",
):
    """Spill → begin-investigation → remediate. Returns ctx with spill, customer, site, tank, route, driver."""
    base = create_active_customer_with_installed_tank(
        tank_kind="USED_OIL", ownership=tank_ownership, capacity_gallons=500, intake_gallons=0,
    )
    driver = create_driver()
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="SPILL", vehicle_capacity_gallons=500)
    drv_headers = make_driver_headers(driver["id"])
    spill = get_success_data(api_client.create_spill_incident(
        create_spill_incident_payload(route["id"], base["site"]["id"],
                                       gallons_spilled=gallons_spilled, cause_code=cause_code),
        drv_headers,
    ))
    spill = get_success_data(api_client.begin_investigation_spill(spill["id"], TEST_USERS["ehs_officer_headers"]))
    spill = get_success_data(api_client.remediate_spill(spill["id"], TEST_USERS["ehs_officer_headers"]))
    return {
        "customer": base["customer"],
        "site": base["site"],
        "tank": base["tank"],
        "driver": driver,
        "route": route,
        "spill": spill,
    }
