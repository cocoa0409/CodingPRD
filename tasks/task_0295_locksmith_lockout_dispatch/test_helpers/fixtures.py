"""Composite setup helpers for multi-step test prerequisites (Locksmith & Lockout Dispatch).

Uses get_success_data() (lenient validator) so setup failures surface as clear
"setup failed" errors, not confusing assertion failures.

Identity threading: the Technician role is entity_backed, so every technician-run
call uses make_technician_headers(tech_id). The Customer role is opaque but
ownership-checked, so customer actions use make_customer_headers(customer_user_id)
matching the job's intake customer_user_id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_service_job_payload,
    create_technician_payload,
    create_job_bay_payload,
    create_dispatch_payload,
    create_bay_booking_payload,
    create_quote_payload,
    create_lock_part_payload,
    create_part_reservation_payload,
    create_payment_payload,
    create_warranty_claim_payload,
)
from .test_users import TEST_USERS, make_technician_headers, make_customer_headers

DISPATCHER = TEST_USERS["dispatcher_headers"]
INVENTORY = TEST_USERS["inventory_manager_headers"]
BILLING = TEST_USERS["billing_agent_headers"]


# ─── Tier 1: single-entity creation ───────────────────────────────────────────
def create_technician(certified_for=None, base_travel_minutes=20, full_name="Tech"):
    """Register an ON_DUTY technician. Returns the technician dict."""
    res = api_client.create_technician(
        create_technician_payload(
            full_name=full_name,
            certified_for=certified_for if certified_for is not None else ["REKEY"],
            base_travel_minutes=base_travel_minutes,
        ),
        DISPATCHER,
    )
    return get_success_data(res)


def create_job(customer_user_id="cust-1", service_type="REKEY", **overrides):
    """Intake an INTAKE service job. Returns the job dict."""
    res = api_client.create_service_job(
        create_service_job_payload(
            customer_user_id=customer_user_id, service_type=service_type, **overrides
        ),
        DISPATCHER,
    )
    return get_success_data(res)


def create_lock_part(units_total=5, sku="SKU-1", **overrides):
    """Create a STOCKED LockPart. Returns the part dict (carries version=1)."""
    res = api_client.create_lock_part(
        create_lock_part_payload(sku=sku, units_total=units_total, **overrides), INVENTORY
    )
    return get_success_data(res)


def create_job_bay(bay_name="Bench"):
    res = api_client.create_job_bay(create_job_bay_payload(bay_name=bay_name), DISPATCHER)
    return get_success_data(res)


# ─── Tier 2: drive a job to a target operational state ─────────────────────────
def dispatch_job(job_id, technician_id, eta_start_minute=605, eta_end_minute=650):
    """Create a dispatch (job INTAKE -> DISPATCHED). Returns the dispatch dict."""
    res = api_client.create_dispatch(
        job_id,
        create_dispatch_payload(technician_id, eta_start_minute, eta_end_minute),
        DISPATCHER,
    )
    return get_success_data(res)


def drive_job_to_on_site(
    customer_user_id="cust-1",
    service_type="REKEY",
    certified_for=None,
    arrived_at_minute=640,
    job_overrides=None,
    base_travel_minutes=20,
):
    """Create technician + job, dispatch, depart, arrive -> job ON_SITE.

    Returns (job, technician, dispatch). The technician is certified for the job's
    service_type by default.
    """
    job_overrides = job_overrides or {}
    certs = certified_for if certified_for is not None else [service_type]
    tech = create_technician(certified_for=certs, base_travel_minutes=base_travel_minutes)
    tech_headers = make_technician_headers(tech["id"])
    job = create_job(
        customer_user_id=customer_user_id, service_type=service_type, **job_overrides
    )
    disp = dispatch_job(job["id"], tech["id"])
    get_success_data(api_client.depart_dispatch(disp["id"], tech_headers))
    arrived = get_success_data(
        api_client.arrive_dispatch(
            disp["id"], {"arrived_at_minute": arrived_at_minute}, tech_headers
        )
    )
    job = get_success_data(api_client.get_service_job(job["id"], DISPATCHER))
    return job, tech, arrived


# ─── Tier 3: quotes on an on-site job ──────────────────────────────────────────
def draft_quote(job_id, technician_id, labor_hours=1.0, part_lines=None):
    """Draft a quote against an ON_SITE job. Returns the DRAFTED quote dict."""
    res = api_client.create_quote(
        job_id,
        create_quote_payload(labor_hours=labor_hours, part_lines=part_lines),
        make_technician_headers(technician_id),
    )
    return get_success_data(res)


def setup_drafted_quote(
    customer_user_id="cust-1",
    service_type="REKEY",
    labor_hours=1.0,
    part_lines=None,
    job_overrides=None,
):
    """ON_SITE job + DRAFTED quote. Returns (job, technician, quote)."""
    job, tech, _ = drive_job_to_on_site(
        customer_user_id=customer_user_id,
        service_type=service_type,
        job_overrides=job_overrides,
    )
    quote = draft_quote(job["id"], tech["id"], labor_hours=labor_hours, part_lines=part_lines)
    return job, tech, quote


def setup_submitted_quote(
    customer_user_id="cust-1",
    service_type="REKEY",
    labor_hours=1.0,
    part_lines=None,
    job_overrides=None,
):
    """ON_SITE job + SUBMITTED quote. Returns (job, technician, quote)."""
    job, tech, quote = setup_drafted_quote(
        customer_user_id=customer_user_id,
        service_type=service_type,
        labor_hours=labor_hours,
        part_lines=part_lines,
        job_overrides=job_overrides,
    )
    quote = get_success_data(
        api_client.submit_quote(quote["id"], make_technician_headers(tech["id"]))
    )
    return job, tech, quote


def setup_approved_quote(
    customer_user_id="cust-1",
    service_type="REKEY",
    labor_hours=1.0,
    part_lines=None,
    job_overrides=None,
):
    """ON_SITE job + APPROVED quote (sets job.amount_due_cents). Returns (job, technician, quote)."""
    job, tech, quote = setup_submitted_quote(
        customer_user_id=customer_user_id,
        service_type=service_type,
        labor_hours=labor_hours,
        part_lines=part_lines,
        job_overrides=job_overrides,
    )
    quote = get_success_data(
        api_client.approve_quote(quote["id"], make_customer_headers(customer_user_id))
    )
    return job, tech, quote


# ─── Tier 4: reservations against a quote ──────────────────────────────────────
def reserve_part(quote_id, part, quantity, technician_id):
    """Reserve `quantity` units of `part` against `quote_id`, using the part's current
    version for OCC. Returns (reservation, refreshed_part)."""
    res = api_client.create_part_reservation(
        create_part_reservation_payload(
            on_site_quote_id=quote_id,
            lock_part_id=part["id"],
            quantity=quantity,
            expected_lockpart_version=part["version"],
        ),
        make_technician_headers(technician_id),
    )
    reservation = get_success_data(res)
    refreshed = get_success_data(api_client.get_lock_part(part["id"], INVENTORY))
    return reservation, refreshed


def setup_drafted_quote_with_reservation(
    customer_user_id="cust-1", units_total=5, quantity=2, sku="SKU-RES"
):
    """ON_SITE job + DRAFTED quote + one RESERVED reservation of `quantity` units.

    Returns (job, technician, quote, part, reservation). The returned `part` is the
    refreshed LockPart (units_available reduced, version bumped).
    """
    part = create_lock_part(units_total=units_total, sku=sku)
    job, tech, quote = setup_drafted_quote(customer_user_id=customer_user_id)
    reservation, part = reserve_part(quote["id"], part, quantity, tech["id"])
    return job, tech, quote, part, reservation


# ─── Tier 5: full lifecycle to closed + paid, then warranty ────────────────────
def setup_paid_completed_job(
    customer_user_id="cust-1", labor_hours=1.0, capture_cents=8000
):
    """ON_SITE job -> APPROVED quote -> capture full payment -> complete-work -> close.

    With REKEY daytime labor_hours=1.0, final_total_cents = 8000, so capture 8000
    brings payment_status to PAID. Returns (job, technician, quote, payment).
    """
    job, tech, quote = setup_approved_quote(
        customer_user_id=customer_user_id, labor_hours=labor_hours
    )
    payment = get_success_data(
        api_client.capture_payment(
            job["id"], create_payment_payload(captured_amount_cents=capture_cents), BILLING
        )
    )
    get_success_data(api_client.complete_work(job["id"], make_technician_headers(tech["id"])))
    job = get_success_data(api_client.close_service_job(job["id"], DISPATCHER))
    return job, tech, quote, payment


def setup_filed_warranty_claim(
    customer_user_id="cust-1",
    refund_amount_cents=8000,
    days_since_close=3,
    capture_cents=8000,
):
    """Closed + PAID job (final 8000) with a FILED warranty claim.

    Returns (job, technician, quote, payment, claim).
    """
    job, tech, quote, payment = setup_paid_completed_job(
        customer_user_id=customer_user_id, capture_cents=capture_cents
    )
    claim = get_success_data(
        api_client.file_warranty_claim(
            job["id"],
            create_warranty_claim_payload(
                days_since_close=days_since_close, refund_amount_cents=refund_amount_cents
            ),
            make_customer_headers(customer_user_id),
        )
    )
    return job, tech, quote, payment, claim
