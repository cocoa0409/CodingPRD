"""Composite setup helpers: multi-step preconditions built only from PRD-declared
endpoints. All helpers use get_success_data (lenient) so setup failures surface as
clear setup errors rather than confusing assertion failures.

Identity threading: after creating an entity_backed entity (Customer / Technician),
every ownership-gated call uses make_customer_headers / make_technician_headers with
the real entity id — never the shared TEST_USERS fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_compliance_incident_payload, create_customer_payload,
    create_damage_claim_payload, create_fleet_contract_payload,
    create_inspection_report_payload, create_quality_audit_payload,
    create_route_payload, create_site_payload, create_subscription_payload,
    create_technician_payload, create_van_payload, create_vehicle_payload,
    create_wash_order_payload, generate_invoice_payload,
    weather_evaluation_payload,
)
from .test_users import (
    TEST_USERS, make_auditor_headers, make_customer_headers, make_technician_headers,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation shortcuts
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_customer(customer_type="RETAIL", **overrides):
    payload = create_customer_payload(customer_type=customer_type, **overrides)
    return get_success_data(api_client.create_customer(payload, ADMIN))


def create_site(customer_id, **overrides):
    payload = create_site_payload(customer_id, **overrides)
    return get_success_data(api_client.create_site(payload, ADMIN))


def create_vehicles(customer_id, site_id, count=1, vehicle_class="SEDAN"):
    """Register `count` vehicles of one class. Returns list of vehicle ids."""
    ids = []
    for _ in range(count):
        payload = create_vehicle_payload(customer_id, site_id, vehicle_class=vehicle_class)
        ids.append(get_success_data(api_client.create_vehicle(payload, ADMIN))["id"])
    return ids


def create_van(reclaim_system="BASIC", tank_capacity_gal=100, load_gallons=None, **overrides):
    payload = create_van_payload(
        reclaim_system=reclaim_system, tank_capacity_gal=tank_capacity_gal, **overrides,
    )
    van = get_success_data(api_client.create_van(payload, ADMIN))
    if load_gallons is not None:
        van = get_success_data(api_client.van_event(
            van["id"], {"event_type": "LOAD_WATER", "gallons": load_gallons}, DISPATCHER,
        ))
    return van


def create_technician(certified=True, **overrides):
    payload = create_technician_payload(water_reclaim_certified=certified, **overrides)
    return get_success_data(api_client.create_technician(payload, ADMIN))


def create_fleet_contract(customer_id, activate=True, **overrides):
    payload = create_fleet_contract_payload(customer_id, **overrides)
    contract = get_success_data(api_client.create_fleet_contract(payload, ADMIN))
    if activate:
        contract = get_success_data(api_client.fleet_contract_event(
            contract["id"], {"event_type": "ACTIVATE"}, ADMIN,
        ))
    return contract


def create_subscription(customer_id, vehicle_id, **overrides):
    payload = create_subscription_payload(customer_id, vehicle_id, **overrides)
    return get_success_data(api_client.create_subscription(payload, ADMIN))


def create_wash_order(customer_id, site_id, vehicle_ids, **overrides):
    payload = create_wash_order_payload(customer_id, site_id, vehicle_ids, **overrides)
    return get_success_data(api_client.create_wash_order(payload, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — customer + site + vehicles
# ---------------------------------------------------------------------------

def setup_customer_site_vehicles(customer_type="RETAIL", num_vehicles=1,
                                 vehicle_class="SEDAN", site_overrides=None):
    """Customer + one site + N vehicles at that site. Returns ctx dict."""
    customer = create_customer(customer_type=customer_type)
    site = create_site(customer["id"], **(site_overrides or {}))
    vehicle_ids = create_vehicles(customer["id"], site["id"], num_vehicles, vehicle_class)
    return {"customer": customer, "site": site, "vehicle_ids": vehicle_ids}


# ---------------------------------------------------------------------------
# Tier 3: order lifecycle progression
# ---------------------------------------------------------------------------

def confirm_order(order_id):
    return get_success_data(api_client.wash_order_event(
        order_id, {"event_type": "CONFIRM"}, DISPATCHER,
    ))


def create_confirmed_order(customer_id, site_id, vehicle_ids, **overrides):
    order = create_wash_order(customer_id, site_id, vehicle_ids, **overrides)
    return confirm_order(order["id"])


def create_route(route_date, van_id, lead_technician_id, shift_start_at=None):
    overrides = {}
    if shift_start_at is not None:
        overrides["shift_start_at"] = shift_start_at
    payload = create_route_payload(route_date, van_id, lead_technician_id, **overrides)
    return get_success_data(api_client.create_route(payload, DISPATCHER))


def add_stop_to_route(route_id, wash_order_id):
    """Append a stop; re-reads the route first so the OCC version is current."""
    route = get_success_data(api_client.get_route(route_id, DISPATCHER))
    return get_success_data(api_client.add_route_stop(
        route_id,
        {"wash_order_id": wash_order_id, "expected_route_version": route["version"]},
        DISPATCHER,
    ))


def route_event(route_id, event_type, **extra):
    payload = {"event_type": event_type}
    payload.update(extra)
    return get_success_data(api_client.route_event(route_id, payload, DISPATCHER))


def stop_event(route_id, stop_id, event_type, technician_id=None):
    headers = make_technician_headers(technician_id) if technician_id else DISPATCHER
    return get_success_data(api_client.route_stop_event(
        route_id, stop_id, {"event_type": event_type}, headers,
    ))


def order_event(order_id, event_type, headers=None, **extra):
    payload = {"event_type": event_type}
    payload.update(extra)
    return get_success_data(api_client.wash_order_event(
        order_id, payload, headers or DISPATCHER,
    ))


def setup_route_with_stop(route_date="2026-08-05", van=None, technician=None,
                          order=None, publish=False, **route_kwargs):
    """Route + one appended stop. Returns ctx dict."""
    if van is None:
        van = create_van(load_gallons=96)
    if technician is None:
        technician = create_technician()
    route = create_route(route_date, van["id"], technician["id"], **route_kwargs)
    ctx = {"route": route, "van": van, "technician": technician, "stop": None}
    if order is not None:
        ctx["stop"] = add_stop_to_route(route["id"], order["id"])
    if publish:
        ctx["route"] = route_event(route["id"], "PUBLISH")
    return ctx


def setup_completed_order(num_vehicles=1, vehicle_class="SEDAN", customer_type="RETAIL",
                          site_overrides=None, window_date="2026-08-05",
                          window_start="13:00:00", window_end="14:00:00",
                          route_date=None, clock_pin=None, van_reclaim="BASIC",
                          van_tank=100, van_load=96, tech_certified=True,
                          requires_inspection=False, vehicles_to_wash=None,
                          contract_overrides=None):
    """Full chain: customer/site/vehicles -> order -> CONFIRM -> van -> technician ->
    route -> stop -> PUBLISH -> ARRIVE -> START -> COMPLETE.

    Returns ctx dict: customer, site, vehicle_ids, order (completed), van, technician,
    route, stop, contract (fleet customers only), washed_ids.
    """
    if clock_pin is not None:
        set_clock(clock_pin)
    ctx = setup_customer_site_vehicles(
        customer_type=customer_type, num_vehicles=num_vehicles,
        vehicle_class=vehicle_class, site_overrides=site_overrides,
    )
    contract = None
    if customer_type == "FLEET":
        contract = create_fleet_contract(ctx["customer"]["id"], **(contract_overrides or {}))
    route_date = route_date or window_date
    order = create_wash_order(
        ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
        scheduled_window_start=f"{window_date}T{window_start}Z",
        scheduled_window_end=f"{window_date}T{window_end}Z",
        requires_inspection=requires_inspection,
    )
    order = confirm_order(order["id"])
    van = create_van(reclaim_system=van_reclaim, tank_capacity_gal=van_tank,
                     load_gallons=van_load)
    technician = create_technician(certified=tech_certified)
    route = create_route(route_date, van["id"], technician["id"])
    stop = add_stop_to_route(route["id"], order["id"])
    route = route_event(route["id"], "PUBLISH")
    stop_event(route["id"], stop["id"], "ARRIVE", technician["id"])
    order_event(order["id"], "START", make_technician_headers(technician["id"]))
    washed = vehicles_to_wash if vehicles_to_wash is not None else ctx["vehicle_ids"]
    order = order_event(
        order["id"], "COMPLETE", make_technician_headers(technician["id"]),
        vehicles_washed_ids=washed,
    )
    ctx.update({
        "order": order, "van": van, "technician": technician, "route": route,
        "stop": stop, "contract": contract, "washed_ids": washed,
    })
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: subscriptions, claims, audits, incidents, invoices
# ---------------------------------------------------------------------------

def pause_subscription(subscription_id, pause_days, customer_id):
    return get_success_data(api_client.subscription_event(
        subscription_id, {"event_type": "PAUSE", "pause_days": pause_days},
        make_customer_headers(customer_id),
    ))


def resume_subscription(subscription_id, customer_id):
    return get_success_data(api_client.subscription_event(
        subscription_id, {"event_type": "RESUME"}, make_customer_headers(customer_id),
    ))


def cancel_subscription(subscription_id, customer_id):
    return get_success_data(api_client.subscription_event(
        subscription_id, {"event_type": "CANCEL"}, make_customer_headers(customer_id),
    ))


def file_damage_claim(wash_order_id, customer_id, **overrides):
    payload = create_damage_claim_payload(wash_order_id, **overrides)
    return get_success_data(api_client.create_damage_claim(
        payload, make_customer_headers(customer_id),
    ))


def review_claim(claim_id, auditor_id="auditor-1"):
    return get_success_data(api_client.damage_claim_event(
        claim_id, {"event_type": "START_REVIEW"}, make_auditor_headers(auditor_id),
    ))


def approve_claim(claim_id, auditor_id="auditor-1", approved_amount_cents=None):
    payload = {"event_type": "APPROVE"}
    if approved_amount_cents is not None:
        payload["approved_amount_cents"] = approved_amount_cents
    return get_success_data(api_client.damage_claim_event(
        claim_id, payload, make_auditor_headers(auditor_id),
    ))


def pay_claim(claim_id, auditor_id="auditor-2"):
    return get_success_data(api_client.damage_claim_event(
        claim_id, {"event_type": "MARK_PAID"}, make_auditor_headers(auditor_id),
    ))


def file_paid_claim(wash_order_id, customer_id, **overrides):
    """Claim -> START_REVIEW -> APPROVE (auditor-1) -> MARK_PAID (auditor-2)."""
    claim = file_damage_claim(wash_order_id, customer_id, **overrides)
    review_claim(claim["id"], "auditor-1")
    approve_claim(claim["id"], "auditor-1")
    return pay_claim(claim["id"], "auditor-2")


def record_audit(wash_order_id, auditor_id="auditor-1", **scores):
    payload = create_quality_audit_payload(wash_order_id, **scores)
    return get_success_data(api_client.create_quality_audit(
        payload, make_auditor_headers(auditor_id),
    ))


def report_incident(site_id, **overrides):
    payload = create_compliance_incident_payload(site_id, **overrides)
    return get_success_data(api_client.create_compliance_incident(payload, COMPLIANCE))


def incident_event(incident_id, event_type):
    return get_success_data(api_client.compliance_incident_event(
        incident_id, {"event_type": event_type}, COMPLIANCE,
    ))


def confirm_incident(site_id, **overrides):
    """Incident at site -> START_REVIEW -> CONFIRM (suspends the site)."""
    incident = report_incident(site_id, **overrides)
    incident_event(incident["id"], "START_REVIEW")
    return incident_event(incident["id"], "CONFIRM")


def generate_invoice(contract_id, period_month, variant):
    payload = generate_invoice_payload(contract_id, period_month, variant)
    return get_success_data(api_client.generate_invoice(payload, DISPATCHER))


def invoice_event(invoice_id, event_type, headers=None):
    return get_success_data(api_client.invoice_event(
        invoice_id, {"event_type": event_type}, headers or DISPATCHER,
    ))


def request_rewash(order_id, customer_id):
    return get_success_data(api_client.rewash_wash_order(
        order_id, make_customer_headers(customer_id),
    ))


def evaluate_weather(evaluation_date, forecast_low_f, precip_probability_pct):
    payload = weather_evaluation_payload(
        evaluation_date, forecast_low_f, precip_probability_pct,
    )
    return get_success_data(api_client.evaluate_weather(payload, DISPATCHER))


def get_order(order_id):
    return get_success_data(api_client.get_wash_order(order_id, DISPATCHER))


def get_route(route_id):
    return get_success_data(api_client.get_route(route_id, DISPATCHER))


def get_van(van_id):
    return get_success_data(api_client.get_van(van_id, DISPATCHER))


def get_site(site_id):
    return get_success_data(api_client.get_site(site_id, DISPATCHER))


def get_subscription(subscription_id):
    return get_success_data(api_client.get_subscription(subscription_id, DISPATCHER))


def list_route_stops(route_id):
    data = get_success_data(api_client.list_route_stops(route_id, DISPATCHER))
    return data if isinstance(data, list) else data.get("data", [])


def list_all_wash_orders():
    data = get_success_data(api_client.list_wash_orders(DISPATCHER, params={"limit": 100}))
    return data if isinstance(data, list) else data.get("data", [])
