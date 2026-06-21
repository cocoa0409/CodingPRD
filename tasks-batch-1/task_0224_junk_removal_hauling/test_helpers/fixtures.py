"""Composite setup helpers for multi-step test prerequisites (Junk Removal & Hauling).

Uses get_success_data() (lenient validator) internally so setup failures surface as
clear "Setup failed" errors instead of confusing downstream assertion failures.

Identity threading: Customer is entity_backed:Customer and CrewLead is
entity_backed:Crew, so every ownership-gated call uses make_customer_headers(customer_id)
or make_crew_lead_headers(crew_id) with the REAL entity id — never the shared
TEST_USERS fallback — because those calls are ownership-gated (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_pricing_policy_payload, create_customer_payload, create_crew_payload,
    create_truck_payload, create_haul_job_payload, create_job_item_payload,
    create_photo_estimate_payload, create_dispatch_payload, create_diversion_payload,
    create_dump_ticket_payload,
)
from .test_users import TEST_USERS, make_customer_headers, make_crew_lead_headers

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_headers"]


# ─── Tier 1: Primitive creators ───────────────────────

def create_policy(**overrides):
    """Create (and thereby ACTIVATE) a pricing policy. Returns the policy resource."""
    return get_success_data(
        api_client.create_pricing_policy(create_pricing_policy_payload(**overrides), ADMIN)
    )


def create_customer(**overrides):
    """Register a customer. Defaults to a high credit limit so fiscal guards do not
    interfere; pass credit_limit_cents to override."""
    overrides.setdefault("credit_limit_cents", 1_000_000)
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), ADMIN)
    )


def create_crew(**overrides):
    """Create an ON_DUTY crew with a 08:00-18:00 shift."""
    return get_success_data(
        api_client.create_crew(create_crew_payload(**overrides), ADMIN)
    )


def create_truck(**overrides):
    """Create an IN_SERVICE truck."""
    return get_success_data(
        api_client.create_truck(create_truck_payload(**overrides), ADMIN)
    )


def create_job(customer_id, **overrides):
    """Create a DRAFT haul job owned by the given customer."""
    headers = make_customer_headers(customer_id)
    return get_success_data(
        api_client.create_haul_job(create_haul_job_payload(customer_id, **overrides), headers)
    )


def add_item(job_id, customer_id, category, quantity=1, **overrides):
    """Add a job item to a DRAFT/ESTIMATED job (customer-owned)."""
    headers = make_customer_headers(customer_id)
    payload = create_job_item_payload(category=category, quantity=quantity, **overrides)
    return get_success_data(api_client.add_job_item(job_id, payload, headers))


def submit_estimate(job_id, customer_id, raw_fraction=0.10, declared_items=None, **overrides):
    """Submit a photo estimate (customer-owned)."""
    headers = make_customer_headers(customer_id)
    if declared_items is not None:
        overrides["declared_items"] = declared_items
    payload = create_photo_estimate_payload(raw_fraction=raw_fraction, **overrides)
    return get_success_data(api_client.submit_photo_estimate(job_id, payload, headers))


def accept_estimate(job_id, estimate_id, customer_id):
    """Accept a submitted estimate, moving the job to ESTIMATED. Returns the job."""
    headers = make_customer_headers(customer_id)
    return get_success_data(api_client.accept_photo_estimate(job_id, estimate_id, headers))


def get_crew_version(crew_id):
    """Read the crew's current version for OCC on dispatch create."""
    crew = get_success_data(api_client.get_crew(crew_id, DISPATCHER))
    return crew["version"]


def get_job_version(job_id, customer_id):
    """Read the job's current version for OCC on revise."""
    job = get_success_data(api_client.get_haul_job(job_id, make_customer_headers(customer_id)))
    return job["version"]


# ─── Tier 2: Estimated job ────────────────────────────

def setup_estimated_job(raw_fraction=0.10, service_type="SCHEDULED", items=None,
                        declared_items=None, credit_limit_cents=1_000_000,
                        policy_overrides=None):
    """Active policy + customer + a job advanced to ESTIMATED via an accepted estimate.

    items: list of (category, quantity) actual JobItems to attach.
    declared_items: declared_items array placed on the estimate for the estimate quote.
    Returns dict with policy, customer, job, estimate, plus the latest job snapshot.
    """
    policy = create_policy(**(policy_overrides or {}))
    customer = create_customer(credit_limit_cents=credit_limit_cents)
    job = create_job(customer["id"], service_type=service_type)
    for category, quantity in (items or []):
        add_item(job["id"], customer["id"], category, quantity)
    estimate = submit_estimate(job["id"], customer["id"], raw_fraction=raw_fraction,
                               declared_items=declared_items)
    job = accept_estimate(job["id"], estimate["id"], customer["id"])
    return {
        "policy": policy,
        "customer": customer,
        "job": job,
        "estimate": estimate,
    }


def setup_estimated_job_with_crew_truck(raw_fraction=0.10, service_type="SCHEDULED",
                                        items=None, declared_items=None,
                                        credit_limit_cents=1_000_000,
                                        crew_overrides=None, policy_overrides=None):
    """As setup_estimated_job, plus an ON_DUTY crew and an IN_SERVICE truck ready to
    dispatch. Returns dict adding crew, truck."""
    ctx = setup_estimated_job(
        raw_fraction=raw_fraction, service_type=service_type, items=items,
        declared_items=declared_items, credit_limit_cents=credit_limit_cents,
        policy_overrides=policy_overrides,
    )
    ctx["crew"] = create_crew(**(crew_overrides or {}))
    ctx["truck"] = create_truck()
    return ctx


# ─── Tier 3: Scheduled / dispatched job ───────────────

def setup_scheduled_job(raw_fraction=0.10, service_type="SCHEDULED", items=None,
                        declared_items=None, credit_limit_cents=1_000_000,
                        window_start_utc="2026-06-10T09:00:00.000Z",
                        window_end_utc="2026-06-10T10:00:00.000Z",
                        crew_overrides=None, policy_overrides=None):
    """Job advanced to SCHEDULED with a RESERVED dispatch on a fresh crew+truck.
    Returns dict adding crew, truck, dispatch, crew_version_before (the version observed
    just before the dispatch was created)."""
    ctx = setup_estimated_job_with_crew_truck(
        raw_fraction=raw_fraction, service_type=service_type, items=items,
        declared_items=declared_items, credit_limit_cents=credit_limit_cents,
        crew_overrides=crew_overrides, policy_overrides=policy_overrides,
    )
    crew_v = get_crew_version(ctx["crew"]["id"])
    ctx["crew_version_before"] = crew_v
    dispatch = get_success_data(api_client.create_dispatch(
        create_dispatch_payload(
            ctx["job"]["id"], ctx["crew"]["id"], ctx["truck"]["id"], crew_v,
            window_start_utc=window_start_utc, window_end_utc=window_end_utc,
        ),
        DISPATCHER,
    ))
    ctx["dispatch"] = dispatch
    return ctx


def setup_dispatched_job(**kwargs):
    """Job advanced to DISPATCHED (dispatch ACTIVE). Same return shape as
    setup_scheduled_job."""
    ctx = setup_scheduled_job(**kwargs)
    ctx["dispatch"] = get_success_data(
        api_client.activate_dispatch(ctx["dispatch"]["id"], DISPATCHER)
    )
    return ctx


def setup_on_site_job(**kwargs):
    """Job advanced to ON_SITE (ready for diversions / dump tickets / load).
    Same return shape as setup_scheduled_job."""
    ctx = setup_dispatched_job(**kwargs)
    crew_headers = make_crew_lead_headers(ctx["crew"]["id"])
    ctx["job"] = get_success_data(api_client.arrive_haul_job(ctx["job"]["id"], crew_headers))
    return ctx


# ─── Tier 4: On-site line items + load ─────────────────

def record_diversion(job_id, crew_id, destination="DONATION", tons=1.0):
    """Record a diversion on an ON_SITE job (crew-owned)."""
    headers = make_crew_lead_headers(crew_id)
    return get_success_data(
        api_client.record_diversion(job_id, create_diversion_payload(destination, tons), headers)
    )


def record_dump_ticket(job_id, crew_id, fee_basis="WEIGHT_BASED",
                       landfill_tons=0.8, landfill_fraction=0.5):
    """Record a dump ticket on an ON_SITE job (crew-owned)."""
    headers = make_crew_lead_headers(crew_id)
    return get_success_data(api_client.record_dump_ticket(
        job_id, create_dump_ticket_payload(fee_basis, landfill_tons, landfill_fraction), headers
    ))


def load_job(job_id, crew_id, measured_truck_fraction):
    """Record the measured load, moving the job to LOADED. Returns the job."""
    headers = make_crew_lead_headers(crew_id)
    return get_success_data(
        api_client.load_haul_job(job_id, {"measured_truck_fraction": measured_truck_fraction}, headers)
    )


def setup_loaded_job(measured_truck_fraction=0.10, diversions=None, dump_tickets=None, **kwargs):
    """Job advanced to LOADED with optional on-site diversions and dump tickets recorded
    before the load. diversions: list of (destination, tons). dump_tickets: list of
    (fee_basis, landfill_tons, landfill_fraction). Returns the on-site ctx plus the loaded
    job and any created diversion/dump records."""
    ctx = setup_on_site_job(**kwargs)
    ctx["diversions"] = []
    for destination, tons in (diversions or []):
        ctx["diversions"].append(record_diversion(ctx["job"]["id"], ctx["crew"]["id"], destination, tons))
    ctx["dump_tickets"] = []
    for fee_basis, landfill_tons, landfill_fraction in (dump_tickets or []):
        ctx["dump_tickets"].append(
            record_dump_ticket(ctx["job"]["id"], ctx["crew"]["id"], fee_basis, landfill_tons, landfill_fraction)
        )
    ctx["job"] = load_job(ctx["job"]["id"], ctx["crew"]["id"], measured_truck_fraction)
    return ctx


# ─── Tier 5: Completed / invoiced job ─────────────────

def complete_job(job_id):
    """Complete a LOADED job (dispatcher), issuing the SERVICE invoice. Returns the job."""
    return get_success_data(api_client.complete_haul_job(job_id, DISPATCHER))


def get_job_invoice(job_id):
    """Fetch the (first) invoice for a job via the job's invoice list."""
    data = get_success_data(api_client.list_job_invoices(job_id, BILLING))
    invoices = data if isinstance(data, list) else data.get("data", [])
    assert invoices, f"Setup failed: no invoice found for job {job_id}"
    return invoices[0]


def setup_completed_job_with_invoice(measured_truck_fraction=0.10, **kwargs):
    """Full lifecycle through COMPLETED with the SERVICE invoice issued. Returns the
    loaded ctx plus the completed job and its issued invoice."""
    ctx = setup_loaded_job(measured_truck_fraction=measured_truck_fraction, **kwargs)
    ctx["job"] = complete_job(ctx["job"]["id"])
    ctx["invoice"] = get_job_invoice(ctx["job"]["id"])
    return ctx


def setup_cancellation_invoice_after_dispatched_cancel(**kwargs):
    """Job taken to DISPATCHED then CANCELLED so a CANCELLATION invoice (fee>0) is issued.
    Returns the dispatched ctx plus the cancelled job and the cancellation invoice."""
    ctx = setup_dispatched_job(**kwargs)
    ctx["job"] = get_success_data(
        api_client.cancel_haul_job(ctx["job"]["id"], make_customer_headers(ctx["customer"]["id"]))
    )
    ctx["invoice"] = get_job_invoice(ctx["job"]["id"])
    return ctx
