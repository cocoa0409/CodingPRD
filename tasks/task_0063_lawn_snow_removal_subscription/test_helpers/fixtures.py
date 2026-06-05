"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared endpoints,
because the server database is reset before each test. Setup calls use the lenient
get_success_data() validator so setup failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_crew_headers,
)
from . import factories as F


# --- low-level single-entity creators (return the created resource dict) ---

def make_customer(email=None, service_zip="10001", full_name="Test Customer"):
    payload = F.create_customer_payload(full_name=full_name, service_zip=service_zip)
    if email is not None:
        payload["email"] = email
    resp = api_client.create_customer(payload, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def make_property(customer_id, zip="10001", address="1 Test St", lawn_area_sqft=3000):
    resp = api_client.create_property(
        F.create_property_payload(customer_id, zip=zip, address=address,
                                  lawn_area_sqft=lawn_area_sqft),
        make_customer_headers(customer_id),
    )
    return get_success_data(resp)


def make_preference(customer_id, property_id, **overrides):
    resp = api_client.create_preference(
        F.create_preference_payload(property_id, **overrides),
        make_customer_headers(customer_id),
    )
    return get_success_data(resp)


def make_contract(customer_id, property_id, **overrides):
    resp = api_client.create_contract(
        F.create_contract_payload(customer_id, property_id, **overrides),
        make_customer_headers(customer_id),
    )
    return get_success_data(resp)


def activate(customer_id, contract_id):
    resp = api_client.activate_contract(contract_id, make_customer_headers(customer_id))
    return get_success_data(resp)


def make_route(region_zip="10001", daily_capacity_minutes=480):
    resp = api_client.create_route(
        F.create_route_payload(region_zip=region_zip,
                               daily_capacity_minutes=daily_capacity_minutes),
        TEST_USERS["dispatcher_headers"],
    )
    return get_success_data(resp)


def make_route_stop(route_id, property_id, **overrides):
    resp = api_client.create_route_stop(
        F.create_route_stop_payload(route_id, property_id, **overrides),
        TEST_USERS["dispatcher_headers"],
    )
    return get_success_data(resp)


def make_crew(route_id, name="Test Crew"):
    resp = api_client.create_crew(
        F.create_crew_payload(route_id, name=name),
        TEST_USERS["dispatcher_headers"],
    )
    return get_success_data(resp)


def make_equipment(route_id=None, equipment_type="PLOW", age_months=12, asset_tag=None):
    overrides = {"equipment_type": equipment_type, "age_months": age_months}
    if route_id is not None:
        overrides["assigned_route_id"] = route_id
    if asset_tag is not None:
        overrides["asset_tag"] = asset_tag
    resp = api_client.create_equipment(
        F.create_equipment_payload(**overrides),
        TEST_USERS["dispatcher_headers"],
    )
    return get_success_data(resp)


def make_weather_reading(region_zip="10001", snow_depth_in=3.0,
                         observed_at="2026-01-10T06:00:00Z"):
    resp = api_client.create_weather_reading(
        F.create_weather_reading_payload(region_zip=region_zip,
                                         snow_depth_in=snow_depth_in,
                                         observed_at=observed_at),
        TEST_USERS["dispatcher_headers"],
    )
    return get_success_data(resp)


def make_visit(contract_id, route_stop_id, service_type="LAWN", **overrides):
    resp = api_client.create_visit(
        F.create_visit_payload(contract_id, route_stop_id,
                               service_type=service_type, **overrides),
        TEST_USERS["dispatcher_headers"],
    )
    return get_success_data(resp)


def dispatch(visit_id):
    resp = api_client.dispatch_visit(visit_id, TEST_USERS["dispatcher_headers"])
    return get_success_data(resp)


def complete(visit_id, crew_id):
    resp = api_client.complete_visit(visit_id, make_crew_headers(crew_id))
    return get_success_data(resp)


def make_skip_request(customer_id, visit_id, reason="test reason"):
    resp = api_client.create_skip_request(
        F.create_skip_request_payload(visit_id, reason=reason),
        make_customer_headers(customer_id),
    )
    return get_success_data(resp)


def approve_skip(skip_id):
    resp = api_client.approve_skip_request(skip_id, TEST_USERS["dispatcher_headers"])
    return get_success_data(resp)


# --- composite scenario builders ---

def setup_customer_property(zip="10001", service_zip=None, **prop_overrides):
    """Customer + one property. Returns (customer, property)."""
    cust = make_customer(service_zip=service_zip or zip)
    prop = make_property(cust["id"], zip=zip, **prop_overrides)
    return cust, prop


def setup_active_contract(zip="10001", contract_overrides=None, prop_overrides=None):
    """Customer + property + ACTIVE contract. Returns (customer, property, contract)."""
    cust = make_customer(service_zip=zip)
    prop = make_property(cust["id"], zip=zip, **(prop_overrides or {}))
    con = make_contract(cust["id"], prop["id"], **(contract_overrides or {}))
    activate(cust["id"], con["id"])
    con = get_success_data(
        api_client.get_contract(con["id"], TEST_USERS["dispatcher_headers"])
    )
    return cust, prop, con


def setup_route_with_stop(zip="10001", contract_overrides=None, stop_overrides=None,
                          prop_overrides=None):
    """Customer + property + ACTIVE contract + route + stop on the property.
    Returns dict with customer, property, contract, route, stop."""
    cust, prop, con = setup_active_contract(
        zip=zip, contract_overrides=contract_overrides, prop_overrides=prop_overrides
    )
    route = make_route(region_zip=zip)
    stop = make_route_stop(route["id"], prop["id"], **(stop_overrides or {}))
    return {
        "customer": cust,
        "property": prop,
        "contract": con,
        "route": route,
        "stop": stop,
    }


def setup_full_dispatch_ready(zip="10001", contract_overrides=None, stop_overrides=None,
                              equipment_overrides=None, prop_overrides=None,
                              with_crew=True):
    """ACTIVE contract + route + stop + (crew) + equipment on the route.
    Everything needed to dispatch and complete a visit. Returns dict."""
    ctx = setup_route_with_stop(
        zip=zip, contract_overrides=contract_overrides,
        stop_overrides=stop_overrides, prop_overrides=prop_overrides,
    )
    if with_crew:
        ctx["crew"] = make_crew(ctx["route"]["id"])
    eo = equipment_overrides or {}
    ctx["equipment"] = make_equipment(route_id=ctx["route"]["id"], **eo)
    return ctx


def setup_dispatched_visit(zip="10001", contract_overrides=None,
                           visit_overrides=None, equipment_overrides=None,
                           with_crew=True):
    """ACTIVE contract + route + stop + crew + equipment + a DISPATCHED visit.
    Returns (ctx, visit) where ctx has customer/contract/route/stop/crew/equipment."""
    ctx = setup_full_dispatch_ready(
        zip=zip, contract_overrides=contract_overrides,
        equipment_overrides=equipment_overrides, with_crew=with_crew,
    )
    visit = make_visit(ctx["contract"]["id"], ctx["stop"]["id"],
                       **(visit_overrides or {}))
    visit = dispatch(visit["id"])
    return ctx, visit


def setup_scheduled_visit(zip="10001", contract_overrides=None, visit_overrides=None,
                          with_equipment=True):
    """ACTIVE contract + route + stop (+ equipment) + a SCHEDULED visit.
    Returns (ctx, visit)."""
    if with_equipment:
        ctx = setup_full_dispatch_ready(
            zip=zip, contract_overrides=contract_overrides, with_crew=False
        )
    else:
        ctx = setup_route_with_stop(zip=zip, contract_overrides=contract_overrides)
    visit = make_visit(ctx["contract"]["id"], ctx["stop"]["id"],
                       **(visit_overrides or {}))
    return ctx, visit


def setup_pending_skip(zip="10001", contract_overrides=None, visit_overrides=None):
    """ACTIVE contract + route + stop + a SCHEDULED visit + a PENDING skip request.
    No equipment (skip path does not need dispatch). Returns (ctx, visit, skip)."""
    ctx = setup_route_with_stop(zip=zip, contract_overrides=contract_overrides)
    visit = make_visit(ctx["contract"]["id"], ctx["stop"]["id"],
                       **(visit_overrides or {}))
    skip = make_skip_request(ctx["customer"]["id"], visit["id"])
    return ctx, visit, skip


def setup_equipment_maintenance_due(zip="10001", age_months=24, runtime_hours=44):
    """Build an Equipment driven to MAINTENANCE_DUE via a completed visit.

    With age 24 and a 44h completed visit: wear = round(2*44 + 5*1 + 0.5*24)
    = round(88 + 5 + 12) = 105 >= 100. Returns (ctx, visit, equipment).
    """
    ctx, visit = setup_dispatched_visit(
        zip=zip,
        contract_overrides={"season": "SUMMER", "contract_price_cents": 20000,
                            "term_months": 4},
        visit_overrides={"service_type": "LAWN", "runtime_hours": runtime_hours},
        equipment_overrides={"equipment_type": "MOWER", "age_months": age_months},
    )
    completed = complete(visit["id"], ctx["crew"]["id"])
    equipment = get_success_data(
        api_client.get_equipment(ctx["equipment"]["id"], TEST_USERS["dispatcher_headers"])
    )
    return ctx, completed, equipment


def get_contract(contract_id):
    return get_success_data(
        api_client.get_contract(contract_id, TEST_USERS["dispatcher_headers"])
    )


def get_customer(customer_id):
    return get_success_data(
        api_client.get_customer(customer_id, TEST_USERS["admin_headers"])
    )


def get_equipment(equipment_id):
    return get_success_data(
        api_client.get_equipment(equipment_id, TEST_USERS["dispatcher_headers"])
    )


def get_visit(visit_id):
    return get_success_data(
        api_client.get_visit(visit_id, TEST_USERS["dispatcher_headers"])
    )


def get_skip(skip_id):
    return get_success_data(
        api_client.get_skip_request(skip_id, TEST_USERS["dispatcher_headers"])
    )


def get_route_stop(stop_id):
    return get_success_data(
        api_client.get_route_stop(stop_id, TEST_USERS["dispatcher_headers"])
    )


def get_route(route_id):
    return get_success_data(
        api_client.get_route(route_id, TEST_USERS["dispatcher_headers"])
    )


def get_weather_reading(reading_id):
    return get_success_data(
        api_client.get_weather_reading(reading_id, TEST_USERS["dispatcher_headers"])
    )
