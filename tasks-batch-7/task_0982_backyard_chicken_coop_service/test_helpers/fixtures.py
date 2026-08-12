"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints, and threads identity correctly: Customer
calls use make_customer_headers(household["id"]); technician-scoped calls use
make_service_tech_headers(technician_id). Setup calls use get_success_data()
so a setup failure surfaces as a clear "Setup step failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_household_payload, create_subscription_plan_payload, create_product_payload,
    create_seasonal_window_payload, create_subscription_payload, create_coop_site_payload,
    create_service_visit_payload, assign_visit_payload, complete_visit_payload,
    create_sitting_engagement_payload, create_sitting_route_payload, add_route_stop_payload,
    create_supply_order_payload, add_order_line_payload, create_invoice_payload,
    wallet_adjustment_payload, plan_change_payload, clock_payload,
)
from .test_users import (
    TEST_USERS, make_customer_headers, make_service_tech_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


# --- logical clock -----------------------------------------------------------

def set_logical_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), ADMIN))


# --- Tier 1: single-resource creation ----------------------------------------

def create_household(zone_code: str = "URBAN", **overrides):
    payload = create_household_payload(zone_code=zone_code, **overrides)
    return get_success_data(api_client.create_household(payload, ADMIN))


def create_plan(**overrides):
    return get_success_data(api_client.create_subscription_plan(
        create_subscription_plan_payload(**overrides), ADMIN))


def create_product(**overrides):
    return get_success_data(api_client.create_product(create_product_payload(**overrides), ADMIN))


def create_window(**overrides):
    return get_success_data(api_client.create_seasonal_window(
        create_seasonal_window_payload(**overrides), ADMIN))


def create_coop(household, coop_capacity_hens: int = 6, **overrides):
    payload = create_coop_site_payload(
        household["id"], coop_capacity_hens=coop_capacity_hens, **overrides)
    return get_success_data(api_client.create_coop_site(
        payload, make_customer_headers(household["id"])))


def create_subscription(household, plan_id: str, current_period_start: str = "2026-05-01T00:00:00Z"):
    payload = create_subscription_payload(
        household["id"], plan_id, current_period_start=current_period_start)
    return get_success_data(api_client.create_subscription(
        payload, make_customer_headers(household["id"])))


def create_visit(household, coop, visit_type: str, scheduled_start: str, scheduled_end: str):
    payload = create_service_visit_payload(
        household["id"], coop["id"], visit_type=visit_type,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end)
    return get_success_data(api_client.create_service_visit(
        payload, make_customer_headers(household["id"])))


# --- Tier 1: visit state progression ------------------------------------------

def assign_visit(visit_id: str, technician_id: str = "tech-1",
                 scheduled_start=None, scheduled_end=None):
    overrides = {}
    if scheduled_start is not None:
        overrides["scheduled_start"] = scheduled_start
    if scheduled_end is not None:
        overrides["scheduled_end"] = scheduled_end
    return get_success_data(api_client.assign_service_visit(
        visit_id, assign_visit_payload(technician_id, **overrides), DISPATCHER))


def check_in_visit(visit_id: str, technician_id: str = "tech-1"):
    return get_success_data(api_client.check_in_visit(
        visit_id, make_service_tech_headers(technician_id)))


def complete_visit(visit_id: str, technician_id: str = "tech-1",
                   observed_flock_size: int = 6, actual_duration_minutes: int = 180):
    return get_success_data(api_client.complete_visit(
        visit_id,
        complete_visit_payload(observed_flock_size=observed_flock_size,
                               actual_duration_minutes=actual_duration_minutes),
        make_service_tech_headers(technician_id)))


def create_scheduled_visit(household, coop, visit_type, scheduled_start, scheduled_end,
                           technician_id: str = "tech-1"):
    visit = create_visit(household, coop, visit_type, scheduled_start, scheduled_end)
    return assign_visit(visit["id"], technician_id)


def create_completed_visit(household, coop, visit_type, scheduled_start, scheduled_end,
                           technician_id: str = "tech-1",
                           observed_flock_size: int = 6, actual_duration_minutes: int = 180):
    visit = create_scheduled_visit(
        household, coop, visit_type, scheduled_start, scheduled_end, technician_id)
    check_in_visit(visit["id"], technician_id)
    return complete_visit(visit["id"], technician_id, observed_flock_size, actual_duration_minutes)


# --- Tier 2: coop installation arc ---------------------------------------------

def install_coop(household, coop, technician_id: str = "tech-1",
                 date: str = "2026-06-01", observed_flock_size: int = 6):
    """Complete a SETUP_INSTALL visit on the coop: PLANNED -> INSTALLED."""
    return create_completed_visit(
        household, coop, "SETUP_INSTALL",
        f"{date}T09:00:00Z", f"{date}T12:00:00Z",
        technician_id=technician_id, observed_flock_size=observed_flock_size,
        actual_duration_minutes=180)


def proof_coop_once(household, coop, technician_id: str = "tech-1", date: str = "2026-06-02"):
    """Complete one PREDATOR_PROOFING visit: grade climbs one rung (NONE->B, B->A)."""
    return create_completed_visit(
        household, coop, "PREDATOR_PROOFING",
        f"{date}T09:00:00Z", f"{date}T11:00:00Z",
        technician_id=technician_id, observed_flock_size=6,
        actual_duration_minutes=90)


def setup_household_with_installed_coop(zone_code: str = "URBAN", coop_capacity_hens: int = 6,
                                        technician_id: str = "tech-1", **household_overrides):
    """Household + coop INSTALLED via a completed SETUP_INSTALL. Returns (household, coop)."""
    household = create_household(zone_code=zone_code, **household_overrides)
    coop = create_coop(household, coop_capacity_hens)
    install_coop(household, coop, technician_id)
    return household, coop


def setup_household_with_grade_b_coop(zone_code: str = "URBAN", coop_capacity_hens: int = 6,
                                      technician_id: str = "tech-1", **household_overrides):
    """Household + coop INSTALLED and proofed once (predator_grade B).
    Returns (household, coop)."""
    household, coop = setup_household_with_installed_coop(
        zone_code, coop_capacity_hens, technician_id, **household_overrides)
    proof_coop_once(household, coop, technician_id)
    return household, coop


# --- Tier 2: subscriptions ------------------------------------------------------

def setup_active_subscription(household, period_start: str = "2026-05-01T00:00:00Z", **plan_overrides):
    """Plan + ACTIVE subscription for the household. Returns (plan, subscription)."""
    plan = create_plan(**plan_overrides)
    subscription = create_subscription(household, plan["id"], period_start)
    return plan, subscription


# --- Tier 2/3: sitting routes and engagements -----------------------------------

def create_route(technician_id: str = "tech-9", route_date: str = "2026-07-10T00:00:00Z",
                 zone_code: str = "URBAN", max_stops: int = 4):
    return get_success_data(api_client.create_sitting_route(
        create_sitting_route_payload(technician_id=technician_id, route_date=route_date,
                                     zone_code=zone_code, max_stops=max_stops),
        DISPATCHER))


def create_published_route(technician_id: str = "tech-9", route_date: str = "2026-07-10T00:00:00Z",
                           zone_code: str = "URBAN", max_stops: int = 4):
    route = create_route(technician_id, route_date, zone_code, max_stops)
    return get_success_data(api_client.publish_sitting_route(route["id"], DISPATCHER))


def create_engagement(household, coop, start_date: str, end_date: str,
                      daily_window_start: str = "08:00"):
    payload = create_sitting_engagement_payload(
        household["id"], coop["id"], start_date=start_date, end_date=end_date,
        daily_window_start=daily_window_start)
    return get_success_data(api_client.create_sitting_engagement(
        payload, make_customer_headers(household["id"])))


def quote_engagement(engagement_id: str):
    return get_success_data(api_client.quote_engagement(engagement_id, DISPATCHER))


def confirm_engagement(engagement_id: str, household):
    return get_success_data(api_client.confirm_engagement(
        engagement_id, make_customer_headers(household["id"])))


def list_engagement_stops(engagement_id: str):
    res = api_client.list_route_stops(DISPATCHER, params={"engagement_id": engagement_id})
    return get_success_data(res)


def setup_quoted_engagement(start_date: str = "2026-07-10T00:00:00Z",
                            end_date: str = "2026-07-11T00:00:00Z",
                            daily_window_start: str = "08:00",
                            zone_code: str = "URBAN"):
    """Household with INSTALLED grade-B coop + a QUOTED engagement.
    Returns (household, coop, engagement)."""
    household, coop = setup_household_with_grade_b_coop(zone_code)
    engagement = create_engagement(household, coop, start_date, end_date, daily_window_start)
    quote_engagement(engagement["id"])
    engagement = get_success_data(api_client.get_sitting_engagement(engagement["id"], DISPATCHER))
    return household, coop, engagement


def setup_confirmed_engagement(start_date: str = "2026-07-10T00:00:00Z",
                               end_date: str = "2026-07-11T00:00:00Z",
                               daily_window_start: str = "08:00",
                               zone_code: str = "URBAN",
                               route_technician_id: str = "tech-9",
                               route_max_stops: int = 4,
                               route_dates=None):
    """Grade-B household + one PUBLISHED route per stop date + CONFIRMED engagement.
    Returns (household, coop, routes, engagement). routes is a list keyed by stop date
    order (stop dates are start_date .. day before end_date)."""
    household, coop, engagement = setup_quoted_engagement(
        start_date, end_date, daily_window_start, zone_code)
    if route_dates is None:
        route_dates = _stop_date_strings(start_date, end_date)
    routes = [create_published_route(route_technician_id, d, zone_code, route_max_stops)
              for d in route_dates]
    engagement = confirm_engagement(engagement["id"], household)
    return household, coop, routes, engagement


def _stop_date_strings(start_date: str, end_date: str):
    """Calendar dates d with start_date <= d < end_date (one stop per night)."""
    from datetime import date, timedelta
    s = date.fromisoformat(start_date[:10])
    e = date.fromisoformat(end_date[:10])
    out = []
    d = s
    while d < e:
        out.append(f"{d.isoformat()}T00:00:00Z")
        d += timedelta(days=1)
    return out


# --- Tier 2/3: supply orders ------------------------------------------------------

def create_order(household, lines=None, fulfillment_visit_id=None):
    """DRAFT order with the given [(sku, quantity)] lines. Returns the order."""
    overrides = {}
    if fulfillment_visit_id is not None:
        overrides["fulfillment_visit_id"] = fulfillment_visit_id
    order = get_success_data(api_client.create_supply_order(
        create_supply_order_payload(household["id"], **overrides),
        make_customer_headers(household["id"])))
    for sku, qty in (lines or []):
        order = get_success_data(api_client.add_order_line(
            order["id"], add_order_line_payload(sku, qty),
            make_customer_headers(household["id"])))
    return order


def place_order(order_id: str, household):
    return get_success_data(api_client.place_order(
        order_id, make_customer_headers(household["id"])))


def create_placed_order(household, lines, fulfillment_visit_id=None):
    order = create_order(household, lines, fulfillment_visit_id)
    return place_order(order["id"], household)


# --- Tier 2/3: invoices -----------------------------------------------------------

def generate_invoice(household_id: str, period_start: str = "2026-05-01T00:00:00Z",
                     period_end: str = "2026-06-01T00:00:00Z"):
    return get_success_data(api_client.create_invoice(
        create_invoice_payload(household_id, period_start=period_start, period_end=period_end),
        BILLING))


def issue_invoice(invoice_id: str):
    return get_success_data(api_client.issue_invoice(invoice_id, BILLING))


def setup_issued_invoice(household, lines, period_start: str = "2026-05-01T00:00:00Z",
                         period_end: str = "2026-06-01T00:00:00Z"):
    """Placed order swept into an invoice that is then ISSUED.
    Returns (order, invoice)."""
    order = create_placed_order(household, lines)
    invoice = generate_invoice(household["id"], period_start, period_end)
    invoice = issue_invoice(invoice["id"])
    return order, invoice


# --- Tier 4: billing / wallet targeting -------------------------------------------

def credit_wallet(household_id: str, amount_cents: int, reason: str = "goodwill"):
    return get_success_data(api_client.adjust_wallet(
        household_id, wallet_adjustment_payload(amount_cents, reason=reason), BILLING))
