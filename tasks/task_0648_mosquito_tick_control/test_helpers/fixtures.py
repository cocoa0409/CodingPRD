"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared endpoints.
The test harness restarts the server (empty DB) before every test, so nothing
carries over. Fixtures use get_success_data() (lenient) internally so that setup
failures surface as clear "Setup failed" errors.

Identity threading: AccountHolder is entity_backed:AccountHolder and CrewTech is
entity_backed:Crew. Ownership-gated calls thread the real entity id through
make_account_holder_headers(ah["id"]) / make_crew_tech_headers(crew["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_account_holder_headers,
    make_crew_tech_headers,
)
from . import factories as F

PLATFORM = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


# --------------------------------------------------------------------------
# Atomic creators (with identity threading)
# --------------------------------------------------------------------------
def create_service_plan(**overrides) -> dict:
    resp = api_client.create_service_plan(F.create_service_plan_payload(**overrides), PLATFORM)
    return get_success_data(resp)


def create_account_holder(**overrides) -> dict:
    # Ensure a unique email per call to avoid uniqueness collisions within a test.
    if "email" not in overrides:
        import uuid
        overrides["email"] = f"ah-{uuid.uuid4().hex[:10]}@example.com"
    resp = api_client.create_account_holder(F.create_account_holder_payload(**overrides), PLATFORM)
    return get_success_data(resp)


def create_crew(**overrides) -> dict:
    resp = api_client.create_crew(F.create_crew_payload(**overrides), PLATFORM)
    return get_success_data(resp)


def create_property(account_holder_id, **overrides) -> dict:
    headers = make_account_holder_headers(account_holder_id)
    resp = api_client.create_property(
        F.create_property_payload(account_holder_id, **overrides), headers
    )
    return get_success_data(resp)


def add_zone(prop, account_holder_id, **overrides) -> dict:
    headers = make_account_holder_headers(account_holder_id)
    resp = api_client.add_zone(prop["id"], F.create_zone_payload(**overrides), headers)
    return get_success_data(resp)


def create_subscription(property_id, plan_id, account_holder_id, **overrides) -> dict:
    headers = make_account_holder_headers(account_holder_id)
    resp = api_client.create_subscription(
        F.create_subscription_payload(property_id, plan_id, **overrides), headers
    )
    return get_success_data(resp)


def activate_subscription(sub_id, account_holder_id) -> dict:
    headers = make_account_holder_headers(account_holder_id)
    return get_success_data(api_client.activate_subscription(sub_id, headers))


def set_clock(iso: str) -> None:
    get_success_data(api_client.set_clock({"to_iso8601": iso}, PLATFORM))


def create_weather_event(**overrides) -> dict:
    return get_success_data(
        api_client.create_weather_event(F.create_weather_event_payload(**overrides), PLATFORM)
    )


# --------------------------------------------------------------------------
# Tier 1/2: Property + zones + plan + holder bundle
# --------------------------------------------------------------------------
def setup_account_property_with_zones(zones=None, region="NE01", lot_size_sqft=6000,
                                      plan_overrides=None):
    """Create a holder, a property with the given zones, and a service plan.

    `zones` is a list of dicts each with zone_type/area_sqft/label (defaults to one
    TURF 4000 zone). Returns (plan, holder, prop, zone_list).
    """
    if zones is None:
        zones = [{"label": "Yard", "zone_type": "TURF", "area_sqft": 4000}]
    plan = create_service_plan(**(plan_overrides or {}))
    holder = create_account_holder()
    prop = create_property(holder["id"], lot_size_sqft=lot_size_sqft, service_region_code=region)
    zone_list = [add_zone(prop, holder["id"], **z) for z in zones]
    return plan, holder, prop, zone_list


def create_active_subscription(billing_mode="PER_VISIT", region="NE01", zones=None,
                               season_start="2026-05-01", season_end="2026-08-31",
                               lot_size_sqft=6000, plan_overrides=None, auto_renew=False):
    """Holder + property + zones + plan + ACTIVE subscription (schedule generated).

    Returns dict with keys: plan, holder, prop, zones, sub.
    """
    plan, holder, prop, zone_list = setup_account_property_with_zones(
        zones=zones, region=region, lot_size_sqft=lot_size_sqft, plan_overrides=plan_overrides
    )
    sub = create_subscription(
        prop["id"], plan["id"], holder["id"],
        billing_mode=billing_mode, season_start_date=season_start,
        season_end_date=season_end, auto_renew=auto_renew,
    )
    sub = activate_subscription(sub["id"], holder["id"])
    return {"plan": plan, "holder": holder, "prop": prop, "zones": zone_list, "sub": sub}


def list_recurring_visits(sub_id):
    """Return the recurring visit list (sorted ascending by creation = sequence)."""
    resp = api_client.list_subscription_visits(sub_id, DISPATCHER)
    data = get_success_data(resp)
    # data may be the array directly (validate via list semantics)
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    return data


# --------------------------------------------------------------------------
# Tier 3: dispatch + log + complete a single visit
# --------------------------------------------------------------------------
def dispatch_visit(route_id, visit_id, expected_version):
    resp = api_client.dispatch_visit(
        route_id,
        {"visit_id": visit_id, "expected_crewroute_version": expected_version},
        DISPATCHER,
    )
    return get_success_data(resp)


def create_route(crew_id, region="NE01", route_date="2026-05-01"):
    resp = api_client.create_crew_route(
        F.create_crew_route_payload(crew_id, region_code=region, route_date=route_date),
        DISPATCHER,
    )
    return get_success_data(resp)


def log_application(visit_id, zone_id, crew_id, **overrides):
    headers = make_crew_tech_headers(crew_id)
    resp = api_client.add_application_log(
        visit_id,
        F.create_application_log_payload(zone_id, crew_id, **overrides),
        headers,
    )
    return get_success_data(resp)


def complete_visit(visit_id, crew_id):
    headers = make_crew_tech_headers(crew_id)
    return get_success_data(api_client.complete_visit(visit_id, headers))


def dispatch_log_complete(visit_id, route_date, zone_id, crew, region="NE01",
                          set_clock_to=None):
    """Create a route for route_date, dispatch the visit, log one application, complete it.

    Returns the completed visit data. If set_clock_to is given the clock is set first
    (anchors completed_at_date).
    """
    if set_clock_to is not None:
        set_clock(set_clock_to)
    route = create_route(crew["id"], region=region, route_date=route_date)
    dispatch_visit(route["id"], visit_id, route["version"])
    log_application(visit_id, zone_id, crew["id"])
    return complete_visit(visit_id, crew["id"])


# --------------------------------------------------------------------------
# Tier 4: a fully completed PER_VISIT visit with its issued invoice
# --------------------------------------------------------------------------
def setup_completed_per_visit_with_invoice(zones=None, lot_size_sqft=6000,
                                           plan_overrides=None, region="NE01"):
    """Build an ACTIVE PER_VISIT subscription, dispatch+log+complete the first recurring
    visit, and return everything plus the issued PER_VISIT invoice.

    Returns dict: plan, holder, prop, zones, sub, crew, visit, invoice.
    """
    ctx = create_active_subscription(
        billing_mode="PER_VISIT", region=region, zones=zones,
        lot_size_sqft=lot_size_sqft, plan_overrides=plan_overrides,
    )
    crew = create_crew(home_region_code=region)
    visits = list_recurring_visits(ctx["sub"]["id"])
    first = visits[0]
    completed = dispatch_log_complete(
        first["id"], first["scheduled_date"], ctx["zones"][0]["id"], crew,
        region=region, set_clock_to="2026-05-01T08:00:00Z",
    )
    # Fetch the per-visit invoice for this visit.
    inv_resp = api_client.list_invoices(BILLING, params={"visit_id": first["id"]})
    inv_data = get_success_data(inv_resp)
    if isinstance(inv_data, dict) and "data" in inv_data:
        inv_data = inv_data["data"]
    invoice = inv_data[0] if inv_data else None
    ctx.update({"crew": crew, "visit": completed, "invoice": invoice})
    return ctx


# --------------------------------------------------------------------------
# Tier 1 (single-purpose): a SCHEDULED recurring visit on WEATHER_HOLD
# --------------------------------------------------------------------------
def setup_visit_on_weather_hold(severity="RAIN_HEAVY", region="NE01",
                                season_end="2026-08-31"):
    """ACTIVE PER_VISIT sub; place its first recurring visit on WEATHER_HOLD via a
    qualifying weather event on its scheduled_date. Returns dict with sub/holder/visit/we.
    """
    ctx = create_active_subscription(region=region, season_end=season_end)
    visits = list_recurring_visits(ctx["sub"]["id"])
    first = visits[0]
    we = create_weather_event(region_code=region, event_date=first["scheduled_date"],
                              severity=severity)
    held = get_success_data(
        api_client.weather_hold(first["id"], {"weather_event_id": we["id"]}, DISPATCHER)
    )
    ctx.update({"visit": held, "weather_event": we})
    return ctx
