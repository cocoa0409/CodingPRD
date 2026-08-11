"""Composite setup helpers.

The server is restarted before every test, so every helper builds its
preconditions from scratch using only PRD-declared endpoints. Setup calls use
the lenient get_success_data() so failures surface as clear "Setup step failed"
errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import DEFAULT_ROUTE_DATE, DEFAULT_WINDOW_END, DEFAULT_WINDOW_START
from .test_users import TEST_USERS, make_customer_headers, make_mechanic_headers

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]

DEFAULT_WINDOW = (DEFAULT_WINDOW_START, DEFAULT_WINDOW_END)

BASIC_TIER = {
    "code": "BASIC",
    "base_price_cents": 4900,
    "included_minutes": 45,
    "overage_rate_cents_per_min": 120,
    "labor_warranty_days": 30,
}
STANDARD_TIER = {
    "code": "STANDARD",
    "base_price_cents": 8900,
    "included_minutes": 75,
    "overage_rate_cents_per_min": 110,
    "labor_warranty_days": 60,
}
PREMIUM_TIER = {
    "code": "PREMIUM",
    "base_price_cents": 14900,
    "included_minutes": 120,
    "overage_rate_cents_per_min": 100,
    "labor_warranty_days": 90,
}


# ---------------------------------------------------------------------------
# Primitive creators (one API call each)
# ---------------------------------------------------------------------------

def make_zone(base_callout_fee_cents=2500, **overrides):
    return get_success_data(api_client.create_zone(
        factories.create_zone_payload(base_callout_fee_cents=base_callout_fee_cents, **overrides), ADMIN))


def make_tier(tier=None, **overrides):
    spec = dict(tier or BASIC_TIER)
    spec.update(overrides)
    return get_success_data(api_client.create_service_tier(
        factories.create_service_tier_payload(**spec), ADMIN))


def make_customer(account_kind="INDIVIDUAL", **overrides):
    return get_success_data(api_client.create_customer(
        factories.create_customer_payload(account_kind=account_kind, **overrides), DISPATCH))


def make_bike(customer_id, **overrides):
    return get_success_data(api_client.create_bike(
        factories.create_bike_payload(customer_id, **overrides), DISPATCH))


def make_mechanic(home_zone_id, ebike_certified=False, **overrides):
    return get_success_data(api_client.create_mechanic(
        factories.create_mechanic_payload(home_zone_id, ebike_certified=ebike_certified, **overrides), ADMIN))


def make_van(zone_id, mechanic_id=None, max_stops_per_day=8, **overrides):
    if mechanic_id is not None:
        overrides.setdefault("mechanic_id", mechanic_id)
    return get_success_data(api_client.create_van(
        factories.create_van_payload(zone_id, max_stops_per_day=max_stops_per_day, **overrides), ADMIN))


def make_part(**overrides):
    return get_success_data(api_client.create_part(factories.create_part_payload(**overrides), ADMIN))


def make_subscription(customer_id, **overrides):
    return get_success_data(api_client.create_subscription(
        factories.create_subscription_payload(customer_id, **overrides), DISPATCH))


def make_request(customer_id, bike_id, zone_id, tier_id, subscription_id=None,
                 window=DEFAULT_WINDOW, **overrides):
    if subscription_id is not None:
        overrides.setdefault("subscription_id", subscription_id)
    return get_success_data(api_client.create_service_request(
        factories.create_service_request_payload(
            customer_id, bike_id, zone_id, tier_id,
            window_start=window[0], window_end=window[1], **overrides),
        DISPATCH))


def make_route_day(van_id, date=DEFAULT_ROUTE_DATE):
    return get_success_data(api_client.create_route_day(
        factories.create_route_day_payload(van_id, date=date), DISPATCH))


def grant_credit(customer_id, amount_cents, reason="goodwill"):
    return get_success_data(api_client.create_credit_adjustment(
        customer_id, {"amount_cents": amount_cents, "reason": reason}, ADMIN))


def receive_stock(van_id, part_id, quantity, note=None):
    payload = {"part_id": part_id, "quantity": quantity, "reason": "RECEIVE"}
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.create_stock_movement(van_id, payload, DISPATCH))


def return_stock(van_id, part_id, quantity):
    return get_success_data(api_client.create_stock_movement(
        van_id, {"part_id": part_id, "quantity": quantity, "reason": "RETURN_TO_WAREHOUSE"}, DISPATCH))


# ---------------------------------------------------------------------------
# Event / action helpers
# ---------------------------------------------------------------------------

def dispatch_stop(route_day_id, request_id, planned_start, planned_end, travel_buffer_minutes=None):
    """Create a route stop (QUOTED -> DISPATCHED). Returns the RouteStop."""
    payload = factories.create_route_stop_payload(request_id, planned_start, planned_end)
    if travel_buffer_minutes is not None:
        payload["travel_buffer_minutes"] = travel_buffer_minutes
    return get_success_data(api_client.create_route_stop(route_day_id, payload, DISPATCH))


def arrive_stop(stop_id, mechanic_id):
    return get_success_data(api_client.route_stop_event(
        stop_id, {"event_type": "ARRIVE"}, make_mechanic_headers(mechanic_id)))


def skip_stop(stop_id, mechanic_id):
    return get_success_data(api_client.route_stop_event(
        stop_id, {"event_type": "SKIP"}, make_mechanic_headers(mechanic_id)))


def start_service(request_id, mechanic_id):
    return get_success_data(api_client.service_request_event(
        request_id, {"event_type": "START_SERVICE"}, make_mechanic_headers(mechanic_id)))


def hold_parts(request_id, mechanic_id):
    return get_success_data(api_client.service_request_event(
        request_id, {"event_type": "HOLD_PARTS"}, make_mechanic_headers(mechanic_id)))


def resume_service(request_id, mechanic_id):
    return get_success_data(api_client.service_request_event(
        request_id, {"event_type": "RESUME"}, make_mechanic_headers(mechanic_id)))


def complete_request(request_id, mechanic_id, labor_minutes):
    return get_success_data(api_client.service_request_event(
        request_id, {"event_type": "COMPLETE", "labor_minutes": labor_minutes},
        make_mechanic_headers(mechanic_id)))


def reserve_part(request_id, part_id, quantity, mechanic_id):
    return get_success_data(api_client.create_part_usage(
        request_id, {"part_id": part_id, "quantity": quantity, "action": "RESERVE"},
        make_mechanic_headers(mechanic_id)))


def release_part(request_id, part_id, quantity, mechanic_id):
    return get_success_data(api_client.create_part_usage(
        request_id, {"part_id": part_id, "quantity": quantity, "action": "RELEASE"},
        make_mechanic_headers(mechanic_id)))


def consume_part(request_id, part_id, quantity, mechanic_id):
    """RESERVE then CONSUME the given quantity of a part for a request."""
    reserve_part(request_id, part_id, quantity, mechanic_id)
    return get_success_data(api_client.create_part_usage(
        request_id, {"part_id": part_id, "quantity": quantity, "action": "CONSUME"},
        make_mechanic_headers(mechanic_id)))


def make_invoice(request_id):
    return get_success_data(api_client.create_invoice(request_id, DISPATCH))


def issue_invoice(invoice_id):
    return get_success_data(api_client.invoice_event(invoice_id, {"event_type": "ISSUE"}, DISPATCH))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def get_request(request_id):
    return get_success_data(api_client.get_service_request(request_id, DISPATCH))


def get_subscription(subscription_id):
    return get_success_data(api_client.get_subscription(subscription_id, DISPATCH))


def get_route_day(route_day_id):
    return get_success_data(api_client.get_route_day(route_day_id, DISPATCH))


def get_route_stop(stop_id):
    return get_success_data(api_client.get_route_stop(stop_id, DISPATCH))


def get_customer(customer_id):
    return get_success_data(api_client.get_customer(customer_id, DISPATCH))


# ---------------------------------------------------------------------------
# Composite setups
# ---------------------------------------------------------------------------

def setup_quoted_request(zone_fee=2500, tier=None, customer_kind="INDIVIDUAL",
                         subscription=None, bike=None, window=DEFAULT_WINDOW,
                         request_overrides=None):
    """Zone + tier + customer + bike (+ optional subscription) + one QUOTED request.

    subscription: None, or a dict of subscription overrides (e.g.
        {"included_tunes_per_period": 4, "discount_pct": 0.10}).
    bike: None, or a dict of bike overrides (e.g. {"bike_type": "EBIKE", "battery_wh": 500}).
    Returns a dict with keys: zone, tier, customer, bike, subscription, request.
    """
    zone = make_zone(zone_fee)
    tier_obj = make_tier(tier)
    customer = make_customer(customer_kind)
    subscription_obj = None
    if subscription is not None:
        subscription_obj = make_subscription(customer["id"], **subscription)
    bike_obj = make_bike(customer["id"], **(bike or {}))
    request = make_request(
        customer["id"], bike_obj["id"], zone["id"], tier_obj["id"],
        subscription_id=subscription_obj["id"] if subscription_obj else None,
        window=window, **(request_overrides or {}))
    return {
        "zone": zone, "tier": tier_obj, "customer": customer, "bike": bike_obj,
        "subscription": subscription_obj, "request": request,
    }


def setup_dispatched_request(zone_fee=2500, tier=None, customer_kind="INDIVIDUAL",
                             subscription=None, bike=None, window=DEFAULT_WINDOW,
                             planned=None, travel_buffer_minutes=None,
                             mechanic_ebike_certified=False, max_stops_per_day=8,
                             route_date=DEFAULT_ROUTE_DATE, parts=None,
                             request_overrides=None):
    """Quoted request + mechanic + van + route day + stop (request DISPATCHED).

    parts: optional list of dicts {"sku", "unit_price_cents", "warranty_days",
        "receive"} — each part is created and `receive` units are stocked on the van.
    Returns a dict with keys: zone, tier, customer, subscription, bike, request,
        mechanic, van, route_day, stop, parts (dict sku -> part).
    """
    ctx = setup_quoted_request(
        zone_fee=zone_fee, tier=tier, customer_kind=customer_kind,
        subscription=subscription, bike=bike, window=window,
        request_overrides=request_overrides)
    mechanic = make_mechanic(ctx["zone"]["id"], ebike_certified=mechanic_ebike_certified)
    van = make_van(ctx["zone"]["id"], mechanic_id=mechanic["id"],
                   max_stops_per_day=max_stops_per_day)
    parts_by_sku = {}
    for spec in (parts or []):
        spec = dict(spec)
        receive_qty = spec.pop("receive", 0)
        part = make_part(**spec)
        if receive_qty:
            receive_stock(van["id"], part["id"], receive_qty)
        parts_by_sku[part["sku"]] = part
    route_day = make_route_day(van["id"], date=route_date)
    planned = planned or window
    stop = dispatch_stop(route_day["id"], ctx["request"]["id"], planned[0], planned[1],
                         travel_buffer_minutes=travel_buffer_minutes)
    ctx.update({
        "mechanic": mechanic, "van": van, "route_day": route_day,
        "stop": stop, "parts": parts_by_sku,
    })
    # Refresh the request so callers see work_status DISPATCHED and the mechanic.
    ctx["request"] = get_request(ctx["request"]["id"])
    return ctx


def setup_in_service_request(**kwargs):
    """Dispatched request + mechanic ARRIVE + START_SERVICE (request IN_SERVICE)."""
    ctx = setup_dispatched_request(**kwargs)
    arrive_stop(ctx["stop"]["id"], ctx["mechanic"]["id"])
    start_service(ctx["request"]["id"], ctx["mechanic"]["id"])
    ctx["request"] = get_request(ctx["request"]["id"])
    ctx["stop"] = get_route_stop(ctx["stop"]["id"])
    return ctx


def setup_completed_job(labor_minutes=40, consume=(), **kwargs):
    """In-service request + optional part consumptions + COMPLETE.

    consume: iterable of (sku, quantity) pairs resolved against the parts created
        via the `parts` kwarg of setup_dispatched_request.
    """
    ctx = setup_in_service_request(**kwargs)
    for sku, qty in consume:
        consume_part(ctx["request"]["id"], ctx["parts"][sku]["id"], qty,
                     ctx["mechanic"]["id"])
    ctx["request"] = complete_request(ctx["request"]["id"], ctx["mechanic"]["id"], labor_minutes)
    return ctx


def setup_issued_invoice(labor_minutes=40, **kwargs):
    """Completed job + DRAFT invoice + ISSUE. Adds ctx["invoice"] (ISSUED)."""
    ctx = setup_completed_job(labor_minutes=labor_minutes, **kwargs)
    invoice = make_invoice(ctx["request"]["id"])
    ctx["invoice"] = issue_invoice(invoice["id"])
    return ctx


def setup_two_stop_route_day(route_date=DEFAULT_ROUTE_DATE):
    """OPEN route day with two PLANNED stops for two different customers.

    Stop windows are far apart so no mechanic overlap can interfere.
    Returns dict with: zone, tier, cust1, cust2, req1, req2, mechanic, van,
    route_day (refreshed, current version), stop1, stop2.
    """
    zone = make_zone(2500)
    tier = make_tier(BASIC_TIER)
    cust1 = make_customer("INDIVIDUAL")
    cust2 = make_customer("INDIVIDUAL")
    bike1 = make_bike(cust1["id"])
    bike2 = make_bike(cust2["id"])
    req1 = make_request(cust1["id"], bike1["id"], zone["id"], tier["id"],
                        window=("2026-05-02T09:00:00Z", "2026-05-02T11:00:00Z"))
    req2 = make_request(cust2["id"], bike2["id"], zone["id"], tier["id"],
                        window=("2026-05-02T12:00:00Z", "2026-05-02T14:00:00Z"))
    mechanic = make_mechanic(zone["id"])
    van = make_van(zone["id"], mechanic_id=mechanic["id"], max_stops_per_day=8)
    route_day = make_route_day(van["id"], date=route_date)
    stop1 = dispatch_stop(route_day["id"], req1["id"],
                          "2026-05-02T09:00:00Z", "2026-05-02T10:00:00Z")
    stop2 = dispatch_stop(route_day["id"], req2["id"],
                          "2026-05-02T12:00:00Z", "2026-05-02T13:00:00Z")
    return {
        "zone": zone, "tier": tier, "cust1": cust1, "cust2": cust2,
        "req1": req1, "req2": req2, "mechanic": mechanic, "van": van,
        "route_day": get_route_day(route_day["id"]),
        "stop1": stop1, "stop2": stop2,
    }
