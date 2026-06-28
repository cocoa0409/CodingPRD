"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed"-style errors instead of confusing assertion failures.

Identity threading: Homeowner is the only entity_backed role. Any ownership-gated call
(accept/decline quote, pay-cash, financing submit/withdraw, file/reopen claim, GET own
resource) MUST use make_homeowner_headers(homeowner_id) with the real Homeowner.id —
never the shared TEST_USERS["homeowner_headers"] constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_homeowner_payload, create_job_payload, create_inspection_payload,
    create_quote_payload, create_crew_payload, create_crew_booking_payload,
    create_install_order_payload, create_financing_application_payload,
    create_service_visit_payload, create_claim_payload,
)
from .test_users import TEST_USERS, make_homeowner_headers

EST = TEST_USERS["estimator_headers"]
INS = TEST_USERS["inspector_headers"]
SCH = TEST_USERS["scheduler_headers"]
WAR = TEST_USERS["warranty_admin_headers"]
FIN = TEST_USERS["finance_partner_headers"]


# ─── Primitive helpers ──────────────────────────────────────────────────────

def create_homeowner(credit_band="PRIME", as_headers=EST, **overrides):
    """Register a homeowner. Returns the Homeowner dict."""
    res = api_client.create_homeowner(
        create_homeowner_payload(credit_band=credit_band, **overrides), as_headers)
    return get_success_data(res)


def create_job(homeowner_id, footprint_sqft=1000, structure_type="CRAWLSPACE", **overrides):
    """Create a LEAD job for an existing homeowner. Returns the Job dict."""
    res = api_client.create_job(
        create_job_payload(homeowner_id, footprint_sqft=footprint_sqft,
                           structure_type=structure_type, **overrides), EST)
    return get_success_data(res)


def create_finalized_inspection(job_id, moisture_pct=65, structural_findings_count=0,
                                **overrides):
    """Create + finalize an inspection on a job. Returns the FINALIZED Inspection dict."""
    draft = get_success_data(api_client.create_inspection(
        job_id, create_inspection_payload(
            moisture_pct=moisture_pct,
            structural_findings_count=structural_findings_count, **overrides), INS))
    return get_success_data(api_client.finalize_inspection(job_id, draft["id"], INS))


def create_sent_quote(job_id, **quote_overrides):
    """Create + send a draft quote on an INSPECTED/QUOTED job. Returns the SENT Quote dict."""
    quote = get_success_data(api_client.create_quote(
        job_id, create_quote_payload(**quote_overrides), EST))
    return get_success_data(api_client.send_quote(quote["id"], EST))


# ─── Tier 1/2: Job progressed to SOLD via accept ────────────────────────────

def setup_sold_job(credit_band="PRIME", footprint_sqft=1000, structure_type="CRAWLSPACE",
                   quote_overrides=None, inspection_overrides=None):
    """Walk an empty DB to a SOLD Job with one ACCEPTED Quote.

    Chain: homeowner -> job -> inspection -> finalize -> quote -> send -> accept.
    Returns dict: homeowner, ho_headers, job, quote, job_version (Job.version after accept).
    """
    quote_overrides = quote_overrides or {}
    inspection_overrides = inspection_overrides or {}
    ho = create_homeowner(credit_band=credit_band)
    ho_headers = make_homeowner_headers(ho["id"])
    job = create_job(ho["id"], footprint_sqft=footprint_sqft, structure_type=structure_type)
    create_finalized_inspection(job["id"], **inspection_overrides)
    quote = create_sent_quote(job["id"], **quote_overrides)
    accepted = get_success_data(api_client.accept_quote(
        quote["id"], {"expected_quote_version": quote["version"]}, ho_headers))
    job_after = get_success_data(api_client.get_job(job["id"], EST))
    return {
        "homeowner": ho,
        "ho_headers": ho_headers,
        "job": job_after,
        "quote": accepted,
        "job_version": job_after["version"],
    }


def setup_sold_cash_job(footprint_sqft=600, quote_overrides=None):
    """SOLD Job financed by CASH (sump-only quote by default, total 395900).

    Extends setup_sold_job with pay-cash. Returns dict adding job_version after pay-cash.
    """
    if quote_overrides is None:
        quote_overrides = {"includes_sump": True}
    ctx = setup_sold_job(footprint_sqft=footprint_sqft, quote_overrides=quote_overrides)
    job_after = get_success_data(api_client.pay_cash(ctx["job"]["id"], ctx["ho_headers"]))
    ctx["job"] = job_after
    ctx["job_version"] = job_after["version"]
    return ctx


# ─── Tier 3: Install order in a target lifecycle stage ──────────────────────

def setup_planned_install_order(footprint_sqft=600, quote_overrides=None,
                                scheduled_start="2026-05-01T08:00:00Z",
                                scheduled_end="2026-05-01T17:00:00Z"):
    """SOLD+CASH Job with a freshly created PLANNED InstallOrder (lifecycle SCHEDULED).

    Returns dict: homeowner, ho_headers, job, quote, install_order.
    """
    ctx = setup_sold_cash_job(footprint_sqft=footprint_sqft, quote_overrides=quote_overrides)
    io = get_success_data(api_client.create_install_order(
        ctx["job"]["id"],
        create_install_order_payload(scheduled_start, scheduled_end, ctx["job_version"]),
        SCH))
    ctx["install_order"] = io
    return ctx


def setup_passed_install_order(footprint_sqft=600, quote_overrides=None,
                               crew_capacity=2,
                               day="2026-05-01"):
    """SOLD+CASH Job with InstallOrder driven to PASSED and a CONFIRMED CrewBooking.

    Chain: planned install order -> crew -> booking -> confirm -> dispatch ->
    advance clock -> start -> inspect-pass.
    Returns dict adding crew, crew_booking, install_order (PASSED).
    """
    start = f"{day}T08:00:00Z"
    end = f"{day}T17:00:00Z"
    ctx = setup_planned_install_order(
        footprint_sqft=footprint_sqft, quote_overrides=quote_overrides,
        scheduled_start=start, scheduled_end=end)
    io_id = ctx["install_order"]["id"]
    crew = get_success_data(api_client.create_crew(
        create_crew_payload(name="Fixture Crew", daily_capacity=crew_capacity), SCH))
    booking = get_success_data(api_client.create_crew_booking(
        create_crew_booking_payload(crew["id"], io_id, start, end), SCH))
    get_success_data(api_client.confirm_crew_booking(booking["id"], SCH))
    get_success_data(api_client.dispatch_install_order(io_id, SCH))
    api_client.set_clock(f"{day}T09:00:00Z", SCH)
    get_success_data(api_client.start_install_order(io_id, SCH))
    passed = get_success_data(api_client.inspect_pass_install_order(io_id, INS))
    ctx["crew"] = crew
    ctx["crew_booking"] = booking
    ctx["install_order"] = passed
    return ctx


# ─── Tier 3/5: Warranted job (via seed fast-forward) ────────────────────────

def setup_warranted_job(credit_band="PRIME"):
    """Provision a Job to WARRANTED with an ACTIVE Warranty via the seed fast-forward.

    Returns dict: homeowner, ho_headers, job_id, warranty_id, install_order_id.
    """
    ho = create_homeowner(credit_band=credit_band, as_headers=WAR)
    seed = get_success_data(api_client.seed_warranted_job(ho["id"], WAR))
    return {
        "homeowner": ho,
        "ho_headers": make_homeowner_headers(ho["id"]),
        "job_id": seed["job_id"],
        "warranty_id": seed["warranty_id"],
        "install_order_id": seed["install_order_id"],
    }


def setup_scheduled_job_seed(credit_band="PRIME", as_headers=SCH):
    """Provision a Job to SCHEDULED via the seed fast-forward (sump-only, CASH, PLANNED IO).

    Returns the seed payload dict: job_id, quote_id, install_order_id, job_version.
    """
    ho = create_homeowner(credit_band=credit_band, as_headers=as_headers)
    seed = get_success_data(api_client.seed_scheduled_job(ho["id"], as_headers))
    seed["homeowner"] = ho
    return seed


# ─── Tier 4/5: Claim lifecycle helpers ──────────────────────────────────────

def setup_open_claim(category="WATER_INTRUSION"):
    """WARRANTED job with one OPEN Claim of the given category.

    Returns dict: job_id, warranty_id, ho_headers, claim, homeowner.
    """
    ctx = setup_warranted_job()
    claim = get_success_data(api_client.create_claim(
        create_claim_payload(ctx["job_id"], ctx["warranty_id"], category),
        ctx["ho_headers"]))
    ctx["claim"] = claim
    return ctx


def setup_resolved_claim():
    """WARRANTED job with a WATER_INTRUSION Claim driven through OPEN -> IN_PROGRESS ->
    RESOLVED (via a completed CLAIM_REPAIR visit).

    Returns dict: job_id, warranty_id, ho_headers, claim (RESOLVED), homeowner.
    """
    ctx = setup_open_claim(category="WATER_INTRUSION")
    claim_id = ctx["claim"]["id"]
    get_success_data(api_client.triage_claim(claim_id, {"accept": True}, WAR))
    sv = get_success_data(api_client.create_service_visit(
        ctx["warranty_id"],
        create_service_visit_payload("CLAIM_REPAIR", "2026-04-10T10:00:00Z", claim_id=claim_id),
        WAR))
    get_success_data(api_client.complete_service_visit(sv["id"], WAR))
    ctx["claim"] = get_success_data(api_client.get_claim(claim_id, WAR))
    return ctx


def setup_scheduled_annual_visit(scheduled_for="2026-09-01T10:00:00Z"):
    """WARRANTED job with an ACTIVE warranty carrying one SCHEDULED ANNUAL ServiceVisit.

    Returns dict: job_id, warranty_id, ho_headers, service_visit, homeowner.
    """
    ctx = setup_warranted_job()
    sv = get_success_data(api_client.create_service_visit(
        ctx["warranty_id"],
        create_service_visit_payload("ANNUAL", scheduled_for), WAR))
    ctx["service_visit"] = sv
    return ctx


# ─── Financing helpers ──────────────────────────────────────────────────────

def setup_submitted_financing(credit_band="PRIME", footprint_sqft=600,
                              quote_overrides=None, term_months=36):
    """SOLD job with a SUBMITTED FinancingApplication against the accepted quote.

    Returns dict: homeowner, ho_headers, job, quote, app, term_months.
    """
    if quote_overrides is None:
        quote_overrides = {"includes_sump": True}
    ctx = setup_sold_job(credit_band=credit_band, footprint_sqft=footprint_sqft,
                         quote_overrides=quote_overrides)
    app = get_success_data(api_client.create_financing_application(
        create_financing_application_payload(
            ctx["job"]["id"], ctx["quote"]["id"], term_months),
        ctx["ho_headers"]))
    ctx["app"] = app
    ctx["term_months"] = term_months
    # Refresh job: financing_status is now APPLIED, version bumped.
    ctx["job"] = get_success_data(api_client.get_job(ctx["job"]["id"], EST))
    ctx["job_version"] = ctx["job"]["version"]
    return ctx
