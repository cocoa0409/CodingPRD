"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be in a state that takes 5-15 API
calls to reach (a COMPLETED job, an INVOICED invoice, a wallet credit from a
granted claim, a crew with a reserved slot, ...). These helpers encapsulate
those chains so tests focus on assertions.

All helpers use get_success_data() (lenient validator) internally, so a broken
precondition surfaces a clear "Setup step failed" error rather than a confusing
assertion failure. Every helper builds its preconditions from scratch — the test
harness restarts the server (empty DB) before each test.

Identity threading: Customer is entity_backed, so every ownership-gated call uses
make_customer_headers(customer["id"]); opaque-role calls use the shared headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_customer_payload,
    create_service_catalog_payload,
    create_crew_payload,
    create_recurring_plan_payload,
    create_cleaning_job_payload,
    create_room_payload,
    create_addon_payload,
    create_booking_payload,
    create_complete_payload,
    create_payment_payload,
    create_claim_payload,
    unique_email,
)
from .test_users import TEST_USERS, make_customer_headers

DISPATCHER = TEST_USERS["dispatcher_headers"]
SERVICE_MANAGER = TEST_USERS["service_manager_headers"]
BILLING = TEST_USERS["billing_headers"]


# ─── Tier 0: Atomic creators ──────────────────────────────────

def create_customer(full_name="Test Customer", email=None):
    """Create an ACTIVE customer. Returns the customer dict."""
    payload = create_customer_payload(full_name=full_name,
                                      email=email or unique_email("cust"))
    return get_success_data(api_client.create_customer(payload, TEST_USERS["customer_headers"]))


def create_catalog(**overrides):
    """Create a service catalog. Returns the catalog dict."""
    return get_success_data(api_client.create_service_catalog(
        create_service_catalog_payload(**overrides), SERVICE_MANAGER))


def create_crew(**overrides):
    """Create an AVAILABLE crew (version 1). Returns the crew dict."""
    return get_success_data(api_client.create_crew(
        create_crew_payload(**overrides), DISPATCHER))


def create_plan(customer_id, cadence="MONTHLY"):
    """Create an ACTIVE recurring plan owned by customer_id."""
    hdr = make_customer_headers(customer_id)
    return get_success_data(api_client.create_recurring_plan(
        create_recurring_plan_payload(customer_id, cadence=cadence), hdr))


def create_job(customer, catalog_id, **overrides):
    """Create a DRAFT cleaning job for `customer` (a customer dict)."""
    hdr = make_customer_headers(customer["id"])
    payload = create_cleaning_job_payload(customer["id"], catalog_id, **overrides)
    return get_success_data(api_client.create_cleaning_job(payload, hdr))


def add_room(job, customer_id, area_label="Room", area_sqft=100, soiling_level="LIGHT"):
    """Attach a room to a DRAFT job owned by customer_id."""
    hdr = make_customer_headers(customer_id)
    return get_success_data(api_client.add_room(
        job["id"],
        create_room_payload(area_label=area_label, area_sqft=area_sqft,
                            soiling_level=soiling_level),
        hdr))


def add_addon(job, customer_id, addon_type):
    """Attach an add-on to a DRAFT job owned by customer_id."""
    hdr = make_customer_headers(customer_id)
    return get_success_data(api_client.add_addon(
        job["id"], create_addon_payload(addon_type=addon_type), hdr))


# ─── Tier 1: Base scenario (customer + catalog + crew) ────────

def setup_base(catalog_overrides=None, crew_overrides=None, with_crew=True):
    """One ACTIVE customer + one catalog + (optionally) one crew.

    Returns dict: {customer, catalog, crew (or None)}.
    """
    customer = create_customer()
    catalog = create_catalog(**(catalog_overrides or {}))
    crew = create_crew(**(crew_overrides or {})) if with_crew else None
    return {"customer": customer, "catalog": catalog, "crew": crew}


# ─── Tier 1: State progression on a single job ────────────────

def quote_job(job, customer_id):
    """Quote a DRAFT job. Returns the QUOTED job dict (carries quoted_price_cents)."""
    hdr = make_customer_headers(customer_id)
    return get_success_data(api_client.quote_job(job["id"], hdr))


def get_crew_version(crew_id):
    """Read a crew's current version (for OCC booking)."""
    crew = get_success_data(api_client.get_crew(crew_id, DISPATCHER))
    return crew["version"]


def book_job(job, crew_id, start_minute, end_minute, expected_crew_version=None):
    """Book a QUOTED job onto a crew slot. Returns the BOOKED job dict.

    If expected_crew_version is None, the live crew version is read first.
    """
    if expected_crew_version is None:
        expected_crew_version = get_crew_version(crew_id)
    payload = create_booking_payload(crew_id, start_minute, end_minute, expected_crew_version)
    return get_success_data(api_client.book_job(job["id"], payload, DISPATCHER))


def start_job(job):
    """Start a BOOKED job. Returns the IN_PROGRESS job dict."""
    return get_success_data(api_client.start_job(job["id"], DISPATCHER))


def complete_job(job, completed_at_minute):
    """Complete an IN_PROGRESS job. Returns the COMPLETED job dict."""
    return get_success_data(api_client.complete_job(
        job["id"], create_complete_payload(completed_at_minute), DISPATCHER))


# ─── Tier 2: Compose a completed job from rooms/add-ons ───────

def setup_completed_job(rooms, *, customer=None, catalog=None, crew=None,
                        addons=None, plan_id=None, move_furniture=False,
                        start_minute=600, end_minute=720, completed_at_minute=800,
                        catalog_overrides=None):
    """Build a job through DRAFT -> ... -> COMPLETED.

    `rooms` is a list of (area_label, area_sqft, soiling_level) tuples added in
    order. `addons` is an optional list of addon_type strings (added after rooms).

    Returns dict: {customer, catalog, crew, job}. `job` is the latest server view.
    """
    if customer is None:
        customer = create_customer()
    if catalog is None:
        catalog = create_catalog(**(catalog_overrides or {}))
    if crew is None:
        crew = create_crew()

    job_overrides = {"move_furniture": move_furniture}
    if plan_id is not None:
        job_overrides["recurring_plan_id"] = plan_id
    job = create_job(customer, catalog["id"], **job_overrides)

    for (label, sqft, soil) in rooms:
        add_room(job, customer["id"], area_label=label, area_sqft=sqft, soiling_level=soil)
    for atype in (addons or []):
        add_addon(job, customer["id"], atype)

    job = quote_job(job, customer["id"])
    job = book_job(job, crew["id"], start_minute, end_minute)
    job = start_job(job)
    job = complete_job(job, completed_at_minute)
    return {"customer": customer, "catalog": catalog, "crew": crew, "job": job}


def setup_quoted_job(rooms, *, customer=None, catalog=None, crew=None,
                     addons=None, plan_id=None, move_furniture=False,
                     catalog_overrides=None):
    """Build a job through DRAFT -> QUOTED. Returns {customer, catalog, crew, job}."""
    if customer is None:
        customer = create_customer()
    if catalog is None:
        catalog = create_catalog(**(catalog_overrides or {}))
    if crew is None:
        crew = create_crew()
    job_overrides = {"move_furniture": move_furniture}
    if plan_id is not None:
        job_overrides["recurring_plan_id"] = plan_id
    job = create_job(customer, catalog["id"], **job_overrides)
    for (label, sqft, soil) in rooms:
        add_room(job, customer["id"], area_label=label, area_sqft=sqft, soiling_level=soil)
    for atype in (addons or []):
        add_addon(job, customer["id"], atype)
    job = quote_job(job, customer["id"])
    return {"customer": customer, "catalog": catalog, "crew": crew, "job": job}


def setup_booked_job(rooms, *, start_minute=600, end_minute=720, **kwargs):
    """Build a job through DRAFT -> QUOTED -> BOOKED. Returns {customer, catalog, crew, job}."""
    ctx = setup_quoted_job(rooms, **kwargs)
    ctx["job"] = book_job(ctx["job"], ctx["crew"]["id"], start_minute, end_minute)
    return ctx


# ─── Tier 3: Invoicing / billing lifecycle ───────────────────

def issue_invoice(job):
    """Issue the per-job invoice on a COMPLETED job. Returns the invoice dict."""
    return get_success_data(api_client.issue_invoice(job["id"], BILLING))


def setup_invoiced_job(rooms, **kwargs):
    """Build a COMPLETED job then issue its invoice.

    Returns dict: {customer, catalog, crew, job, invoice}. `job` is re-read after
    issuance so the caller sees the now-populated settled_price_cents, invoice_id,
    and billing_status INVOICED (the pre-invoice snapshot still has them null).
    """
    ctx = setup_completed_job(rooms, **kwargs)
    ctx["invoice"] = issue_invoice(ctx["job"])
    ctx["job"] = get_job(ctx["job"]["id"])
    return ctx


def record_payment(invoice_id, amount_cents, expected_invoice_version, method="CARD"):
    """Record a payment against an OPEN invoice. Returns the payment dict."""
    return get_success_data(api_client.record_payment(
        invoice_id,
        create_payment_payload(amount_cents, expected_invoice_version, method=method),
        BILLING))


# ─── Tier 4: Guarantee grant -> wallet credit accumulation ────

def grant_guarantee_credit(customer, catalog, crew, *, start_minute=600, end_minute=720,
                           completed_at_minute=800, filed_at_minute=900):
    """Run a full origin-job -> completed -> filed claim -> GRANTED cycle so the
    customer accrues one GUARANTEE_CREDIT (2000 cents) wallet entry.

    Reuses the supplied customer/catalog/crew. Returns the granted claim dict.
    Booking uses the supplied start/end window; choose a non-overlapping window
    when chaining multiple jobs onto the same crew.
    """
    hdr = make_customer_headers(customer["id"])
    job = create_job(customer, catalog["id"])
    add_room(job, customer["id"], area_label="SeedRoom", area_sqft=100, soiling_level="LIGHT")
    job = quote_job(job, customer["id"])
    job = book_job(job, crew["id"], start_minute, end_minute)
    job = start_job(job)
    job = complete_job(job, completed_at_minute)
    claim = get_success_data(api_client.file_claim(
        create_claim_payload(job["id"], filed_at_minute, reason="seed credit"), hdr))
    return get_success_data(api_client.grant_claim(claim["id"], SERVICE_MANAGER))


def setup_customer_with_wallet_credit():
    """Create a customer who holds exactly 2000 cents wallet credit from one
    GRANTED guarantee claim. Returns dict: {customer, catalog, crew}.

    The customer/catalog/crew are reusable for a follow-on billing job; the seed
    job occupies the crew window [0, 120).
    """
    base = setup_base()
    grant_guarantee_credit(base["customer"], base["catalog"], base["crew"],
                           start_minute=0, end_minute=120,
                           completed_at_minute=200, filed_at_minute=300)
    return base


# ─── Helpers for reading current state ────────────────────────

def get_job(job_id, headers=None):
    return get_success_data(api_client.get_cleaning_job(job_id, headers or SERVICE_MANAGER))


def get_customer(customer_id, headers=None):
    return get_success_data(api_client.get_customer(customer_id, headers or SERVICE_MANAGER))


def get_invoice(invoice_id, headers=None):
    return get_success_data(api_client.get_invoice(invoice_id, headers or BILLING))


def get_slot_status_via_crew(crew_id, slot_id):
    """Return a slot's status by listing the crew's slots and matching id.
    Slots have no direct GET endpoint, so we read them through the crew listing.
    """
    data = get_success_data(api_client.list_crew_scheduled_slots(crew_id, DISPATCHER))
    for slot in data:
        if slot["id"] == slot_id:
            return slot["status"]
    return None


def count_reserved_slots(crew_id):
    """Count RESERVED slots on a crew via the status-filtered list endpoint."""
    data, meta = _paginated(api_client.list_crew_scheduled_slots(
        crew_id, DISPATCHER, params={"status": "RESERVED"}))
    return meta["total_count"]


def _paginated(response):
    """Local thin wrapper so fixtures can read total_count without importing the
    framework validator at module import boundaries."""
    body = response.json()
    return body["data"], body["meta"]
