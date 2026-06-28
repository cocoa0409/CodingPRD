"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient) internally so a broken setup surfaces as a clear
"Setup failed" error rather than a confusing assertion failure later.

Identity threading: entity_backed roles (Customer, Mechanic, FleetManager) must call
with the actual entity id via make_*_headers(); opaque roles (Dispatcher, PlatformAdmin)
use the shared TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_catalog_part_payload, create_fleet_account_payload, create_customer_payload,
    create_mechanic_payload, create_service_request_payload, create_quote_payload,
    create_dispatch_payload, create_part_line_payload, create_inspection_finding_payload,
    create_resolve_addons_payload, create_approve_quote_payload, create_finish_payload,
    create_warranty_claim_payload,
)
from .test_users import (
    TEST_USERS, make_customer_headers, make_mechanic_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Low-level seeding
# ─────────────────────────────────────────────────────────────────────────────

def set_clock(to_iso8601="2026-04-01T00:00:00Z"):
    """Reset the logical clock to a known instant."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_catalog_part(wholesale_cost_cents=4000, sku="CP-1", name="Part"):
    return get_success_data(api_client.create_catalog_part(
        create_catalog_part_payload(sku=sku, name=name,
                                    wholesale_cost_cents=wholesale_cost_cents), ADMIN))


def create_fleet_account(credit_limit_cents=1_000_000, labor_discount_pct=0,
                         company_name="Fleet"):
    return get_success_data(api_client.create_fleet_account(
        create_fleet_account_payload(company_name=company_name,
                                     credit_limit_cents=credit_limit_cents,
                                     labor_discount_pct=labor_discount_pct), ADMIN))


def create_customer(home_zone_code="Z1", fleet_account_id=None, email="c@x.com",
                    full_name="Customer"):
    payload = create_customer_payload(email=email, full_name=full_name,
                                      home_zone_code=home_zone_code)
    if fleet_account_id is not None:
        payload["fleet_account_id"] = fleet_account_id
    return get_success_data(api_client.create_customer(payload, ADMIN))


def create_mechanic(zone_code="Z1", skill_tier="TIER2", labor_rate_cents_per_hour=9000,
                    full_name="Mechanic"):
    return get_success_data(api_client.create_mechanic(
        create_mechanic_payload(full_name=full_name, zone_code=zone_code,
                                skill_tier=skill_tier,
                                labor_rate_cents_per_hour=labor_rate_cents_per_hour), ADMIN))


def create_service_request(customer_id, vehicle_vin="1HGCM82633A004352",
                           symptom_text="symptom", severity=None):
    payload = create_service_request_payload(customer_id, vehicle_vin=vehicle_vin,
                                             symptom_text=symptom_text)
    if severity is not None:
        payload["severity"] = severity
    return get_success_data(api_client.create_service_request(
        payload, make_customer_headers(customer_id)))


def _sr_version(sr_id):
    return get_success_data(api_client.get_service_request(sr_id, DISPATCHER))["version"]


# ─────────────────────────────────────────────────────────────────────────────
# Tier 1: state-progression primitives on a single ServiceRequest
# ─────────────────────────────────────────────────────────────────────────────

def send_quote(sr_id, mechanic_id, estimated_labor_hours=1.0, estimated_parts_cents=0,
               labor_rate_cents_per_hour=9000, tow_fee_cents=0, diagnosis_text="diag"):
    """Mechanic sends a quote against the request; returns the Quote."""
    return get_success_data(api_client.send_quote(
        sr_id,
        create_quote_payload(diagnosis_text=diagnosis_text,
                             estimated_labor_hours=estimated_labor_hours,
                             estimated_parts_cents=estimated_parts_cents,
                             labor_rate_cents_per_hour=labor_rate_cents_per_hour,
                             tow_fee_cents=tow_fee_cents),
        make_mechanic_headers(mechanic_id)))


def approve_quote(quote_id, customer_id, sr_id):
    """Customer approves a SENT quote using the current SR version. Returns the Quote."""
    version = _sr_version(sr_id)
    return get_success_data(api_client.approve_quote(
        quote_id, create_approve_quote_payload(version),
        make_customer_headers(customer_id)))


def dispatch(sr_id, mechanic_id, routing_mode="ON_SITE",
             scheduled_start_utc="2026-04-02T09:00:00Z",
             scheduled_end_utc="2026-04-02T10:00:00Z"):
    """Dispatcher dispatches the request using the current SR version. Returns JobVisit."""
    version = _sr_version(sr_id)
    return get_success_data(api_client.dispatch(
        sr_id,
        create_dispatch_payload(mechanic_id, version, routing_mode=routing_mode,
                                scheduled_start_utc=scheduled_start_utc,
                                scheduled_end_utc=scheduled_end_utc),
        DISPATCHER))


# ─────────────────────────────────────────────────────────────────────────────
# Tier 2 / 3: composite scenarios reaching common lifecycle stages
# ─────────────────────────────────────────────────────────────────────────────

def setup_quoted_request(home_zone_code="Z1", fleet_account_id=None,
                         estimated_labor_hours=1.0, estimated_parts_cents=0,
                         labor_rate_cents_per_hour=9000, tow_fee_cents=0,
                         mechanic_zone="Z1", mechanic_tier="TIER2",
                         mechanic_rate=9000, vehicle_vin="1HGCM82633A004352",
                         email="c@x.com"):
    """Active customer + mechanic + a ServiceRequest in QUOTED with a SENT quote.

    Returns dict: customer, mechanic, service_request, quote.
    """
    set_clock()
    customer = create_customer(home_zone_code=home_zone_code,
                               fleet_account_id=fleet_account_id, email=email)
    mechanic = create_mechanic(zone_code=mechanic_zone, skill_tier=mechanic_tier,
                               labor_rate_cents_per_hour=mechanic_rate)
    sr = create_service_request(customer["id"], vehicle_vin=vehicle_vin)
    quote = send_quote(sr["id"], mechanic["id"],
                       estimated_labor_hours=estimated_labor_hours,
                       estimated_parts_cents=estimated_parts_cents,
                       labor_rate_cents_per_hour=labor_rate_cents_per_hour,
                       tow_fee_cents=tow_fee_cents)
    return {"customer": customer, "mechanic": mechanic, "service_request": sr,
            "quote": quote}


def setup_approved_request(**kwargs):
    """ServiceRequest driven to APPROVED with its quote APPROVED.

    Accepts the same overrides as setup_quoted_request. Returns the same dict
    (service_request re-fetched so it reflects APPROVED + estimate_total_cents).
    """
    ctx = setup_quoted_request(**kwargs)
    approve_quote(ctx["quote"]["id"], ctx["customer"]["id"], ctx["service_request"]["id"])
    ctx["service_request"] = get_success_data(
        api_client.get_service_request(ctx["service_request"]["id"], DISPATCHER))
    return ctx


def setup_dispatched_request(routing_mode="ON_SITE",
                             scheduled_start_utc="2026-04-02T09:00:00Z",
                             scheduled_end_utc="2026-04-02T10:00:00Z",
                             **kwargs):
    """ServiceRequest DISPATCHED with a SCHEDULED JobVisit. Adds 'job_visit' to ctx."""
    if routing_mode == "TOW_TO_SHOP":
        kwargs.setdefault("mechanic_tier", "TIER3")
    ctx = setup_approved_request(**kwargs)
    jv = dispatch(ctx["service_request"]["id"], ctx["mechanic"]["id"],
                  routing_mode=routing_mode,
                  scheduled_start_utc=scheduled_start_utc,
                  scheduled_end_utc=scheduled_end_utc)
    ctx["job_visit"] = jv
    return ctx


def setup_in_progress_request(routing_mode="ON_SITE", **kwargs):
    """ServiceRequest IN_PROGRESS: visit departed + start-work done.

    For ON_SITE the visit reaches ON_SITE_WORKING; for TOW_TO_SHOP it reaches AT_SHOP.
    Returns ctx with refreshed 'service_request' and 'job_visit'.
    """
    ctx = setup_dispatched_request(routing_mode=routing_mode, **kwargs)
    mech_headers = make_mechanic_headers(ctx["mechanic"]["id"])
    jv_id = ctx["job_visit"]["id"]
    get_success_data(api_client.depart(jv_id, mech_headers))
    get_success_data(api_client.start_work(jv_id, mech_headers))
    ctx["job_visit"] = get_success_data(api_client.get_job_visit(jv_id, DISPATCHER))
    ctx["service_request"] = get_success_data(
        api_client.get_service_request(ctx["service_request"]["id"], DISPATCHER))
    return ctx


def source_part_line(sr_id, mechanic_id, catalog_part_id, quantity=1):
    """Mechanic sources a non-add-on part line. Returns the PartLine."""
    return get_success_data(api_client.source_part_line(
        sr_id, create_part_line_payload(catalog_part_id, quantity=quantity),
        make_mechanic_headers(mechanic_id)))


def add_finding(sr_id, mechanic_id, job_visit_id, description="finding",
                recommended_part_id=None, recommended_quantity=None,
                add_on_labor_hours=None):
    """Mechanic records an inspection finding. Returns the InspectionFinding."""
    overrides = {}
    if recommended_part_id is not None:
        overrides["recommended_part_id"] = recommended_part_id
    if recommended_quantity is not None:
        overrides["recommended_quantity"] = recommended_quantity
    if add_on_labor_hours is not None:
        overrides["add_on_labor_hours"] = add_on_labor_hours
    return get_success_data(api_client.create_inspection_finding(
        sr_id,
        create_inspection_finding_payload(job_visit_id, description=description, **overrides),
        make_mechanic_headers(mechanic_id)))


def resolve_addons(sr_id, customer_id, decisions):
    """Customer resolves add-ons. decisions is a list of {finding_id, decision}."""
    return get_success_data(api_client.resolve_addons(
        sr_id, create_resolve_addons_payload(decisions),
        make_customer_headers(customer_id)))


def finish_visit(job_visit_id, mechanic_id, logged_labor_hours=1.0, payment_method="CARD"):
    """Mechanic finishes the visit. Returns the JobVisit."""
    return get_success_data(api_client.finish(
        job_visit_id,
        create_finish_payload(logged_labor_hours, payment_method=payment_method),
        make_mechanic_headers(mechanic_id)))


def setup_completed_request(routing_mode="ON_SITE", logged_labor_hours=1.0,
                            payment_method="CARD", **kwargs):
    """ServiceRequest driven all the way to COMPLETED (visit FINISHED, Payment INVOICED).

    Returns ctx with refreshed 'service_request', 'job_visit'.
    """
    ctx = setup_in_progress_request(routing_mode=routing_mode, **kwargs)
    finish_visit(ctx["job_visit"]["id"], ctx["mechanic"]["id"],
                 logged_labor_hours=logged_labor_hours, payment_method=payment_method)
    ctx["job_visit"] = get_success_data(
        api_client.get_job_visit(ctx["job_visit"]["id"], DISPATCHER))
    ctx["service_request"] = get_success_data(
        api_client.get_service_request(ctx["service_request"]["id"], DISPATCHER))
    return ctx


def get_request_payment(sr_id):
    """Return the first Payment for a request (the 1:1 invoice), or None."""
    data, _meta = _list(api_client.list_service_request_payments(sr_id, DISPATCHER))
    return data[0] if data else None


def file_warranty_claim(sr_id, customer_id, reason_text="fault recurred"):
    """Customer files a warranty claim against a COMPLETED request. Returns the claim."""
    return get_success_data(api_client.file_warranty_claim(
        sr_id, create_warranty_claim_payload(reason_text=reason_text),
        make_customer_headers(customer_id)))


def _list(response):
    """Internal helper to peel a paginated list response into (data, meta)."""
    body = response.json()
    return body["data"], body.get("meta", {})
