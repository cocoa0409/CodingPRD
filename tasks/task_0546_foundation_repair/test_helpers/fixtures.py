"""Composite setup helpers for multi-step Foundation Repair test prerequisites.

Every interesting claim in this domain requires the system to be walked through a long
pipeline (lead -> inspection -> scope -> quote -> job -> warranty -> claim). These helpers
encapsulate those chains so tests focus on assertions, not plumbing.

All setup calls use get_success_data() (the lenient validator) so a broken precondition
surfaces as a clear "Setup failed" rather than a confusing mid-test assertion error.
The harness restarts the server before every test, so each helper builds its state from an
empty database using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_lead_payload,
    create_inspection_payload,
    complete_inspection_payload,
    create_scope_payload,
    create_quote_payload,
    create_crew_payload,
    create_permit_payload,
    schedule_job_payload,
    complete_job_payload,
    create_claim_payload,
)
from .test_users import TEST_USERS, make_customer_headers

SALES = TEST_USERS["sales_agent_headers"]
ENGINEER = TEST_USERS["field_engineer_headers"]
OPS = TEST_USERS["ops_coordinator_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ─── Clock helper ─────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the server logical clock (Admin-only, PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: single-entity builders ──────────────────────────────────────────

def create_lead(region_code: str = "NORTH", **overrides) -> dict:
    res = api_client.create_lead(
        create_lead_payload(region_code=region_code, **overrides), SALES
    )
    return get_success_data(res)


def create_crew(region_code: str = "NORTH", crew_name: str = "Test Crew") -> dict:
    res = api_client.create_crew(
        create_crew_payload(crew_name=crew_name, region_code=region_code), ADMIN
    )
    return get_success_data(res)


def create_completed_inspection(lead_id: str, soil_class: str = "STABLE",
                                crack_severity: int = 1, max_crack_width_mm: float = 2.0,
                                settlement_inches: float = 0.5) -> dict:
    """Book an inspection and complete it with an assessment (Inspection -> COMPLETED)."""
    insp = get_success_data(
        api_client.create_inspection(create_inspection_payload(lead_id), SALES)
    )
    return get_success_data(
        api_client.complete_inspection(
            insp["id"],
            complete_inspection_payload(
                soil_class=soil_class,
                crack_severity=crack_severity,
                max_crack_width_mm=max_crack_width_mm,
                settlement_inches=settlement_inches,
            ),
            ENGINEER,
        )
    )


def create_draft_scope(lead: dict, inspection_id: str, **scope_overrides) -> dict:
    """Create a DRAFT EngineeringScope against the lead's current version."""
    res = api_client.create_scope(
        create_scope_payload(
            lead["id"], inspection_id, expected_lead_version=lead["version"],
            **scope_overrides
        ),
        ENGINEER,
    )
    return get_success_data(res)


def create_engineered_scope(lead: dict, inspection_id: str, **scope_overrides) -> dict:
    """Create a scope and finalize it to ENGINEERED."""
    scope = create_draft_scope(lead, inspection_id, **scope_overrides)
    return get_success_data(api_client.finalize_scope(scope["id"], ENGINEER))


# ─── Tier 2: scope / quote scenario ──────────────────────────────────────────

def setup_sent_quote(*, region_code: str = "NORTH", soil_class: str = "STABLE",
                     financing_plan: str = "CASH", pier_count: int = 8,
                     anchor_count: int = 0, avg_pier_depth_ft: float = 18,
                     access_difficulty: str = "EASY",
                     supplemental_engineering: bool = False,
                     finalize_scope: bool = True) -> dict:
    """Walk lead -> completed inspection -> (engineered) scope -> DRAFT quote -> SENT quote.

    Returns a context dict: lead, inspection, scope, quote (freshly SENT).
    Set finalize_scope=False to leave the scope in DRAFT (for ERR_SCOPE_NOT_ENGINEERED).
    """
    lead = create_lead(region_code=region_code)
    inspection = create_completed_inspection(lead["id"], soil_class=soil_class)
    scope_builder = create_engineered_scope if finalize_scope else create_draft_scope
    scope = scope_builder(
        lead, inspection["id"],
        pier_count=pier_count, anchor_count=anchor_count,
        avg_pier_depth_ft=avg_pier_depth_ft, access_difficulty=access_difficulty,
        supplemental_engineering=supplemental_engineering,
    )
    quote = get_success_data(
        api_client.create_quote(
            create_quote_payload(lead["id"], scope["id"], financing_plan), SALES
        )
    )
    quote = get_success_data(api_client.send_quote(quote["id"], SALES))
    return {"lead": lead, "inspection": inspection, "scope": scope, "quote": quote}


def setup_draft_quote(**kwargs) -> dict:
    """Same as setup_sent_quote but leaves the quote in DRAFT (send skipped)."""
    lead = create_lead(region_code=kwargs.get("region_code", "NORTH"))
    inspection = create_completed_inspection(
        lead["id"], soil_class=kwargs.get("soil_class", "STABLE")
    )
    scope = create_engineered_scope(
        lead, inspection["id"],
        pier_count=kwargs.get("pier_count", 8),
        anchor_count=kwargs.get("anchor_count", 0),
        avg_pier_depth_ft=kwargs.get("avg_pier_depth_ft", 18),
        access_difficulty=kwargs.get("access_difficulty", "EASY"),
        supplemental_engineering=kwargs.get("supplemental_engineering", False),
    )
    quote = get_success_data(
        api_client.create_quote(
            create_quote_payload(lead["id"], scope["id"],
                                 kwargs.get("financing_plan", "CASH")),
            SALES,
        )
    )
    return {"lead": lead, "inspection": inspection, "scope": scope, "quote": quote}


# ─── Tier 3: acceptance / job builders ───────────────────────────────────────

def fetch_job_for_quote(quote_id: str) -> dict:
    """Reverse-lookup the Job spawned by accepting a quote."""
    jobs = get_success_data(
        api_client.list_jobs(OPS, params={"quote_id": quote_id})
    )
    assert jobs, f"no job found for quote {quote_id}"
    return jobs[0]


def accept_quote_and_get_job(ctx: dict) -> dict:
    """Accept the SENT quote in ctx (as its owning Customer) and return the new Job."""
    lead = ctx["lead"]
    get_success_data(
        api_client.accept_quote(ctx["quote"]["id"], make_customer_headers(lead["id"]))
    )
    return fetch_job_for_quote(ctx["quote"]["id"])


def setup_accepted_job(**kwargs) -> dict:
    """setup_sent_quote + accept. Returns ctx with an added 'job' (UNSCHEDULED)."""
    ctx = setup_sent_quote(**kwargs)
    ctx["job"] = accept_quote_and_get_job(ctx)
    return ctx


def approve_permit_for_job(job_id: str) -> dict:
    """Open a permit for the job and approve it (Job.permit_status -> APPROVED)."""
    permit = get_success_data(
        api_client.create_permit(create_permit_payload(job_id), OPS)
    )
    return get_success_data(
        api_client.decide_permit(permit["id"], {"decision": "APPROVE"}, OPS)
    )


def setup_job_ready_to_schedule(*, crew_region: str = "NORTH", **kwargs) -> dict:
    """Accepted job + approved permit + a crew. Returns ctx with 'job', 'permit', 'crew'."""
    ctx = setup_accepted_job(**kwargs)
    ctx["permit"] = approve_permit_for_job(ctx["job"]["id"])
    ctx["crew"] = create_crew(region_code=crew_region)
    return ctx


def setup_two_jobs_first_scheduled(*, first_start: str = "2026-06-01T08:00:00Z",
                                   first_end: str = "2026-06-01T12:00:00Z") -> dict:
    """One NORTH lead + one ENGINEERED scope backing two accepted quotes -> two jobs, both
    permit-approved, sharing one NORTH crew; job1 is scheduled for [first_start, first_end).

    Returns {lead, crew, job1 (SCHEDULED), job2 (permit-approved, UNSCHEDULED)}.
    Used for crew half-open overlap (double-book) and abutting-window tests.
    """
    lead = create_lead(region_code="NORTH")
    inspection = create_completed_inspection(lead["id"], soil_class="STABLE")
    scope = create_engineered_scope(lead, inspection["id"], pier_count=8, anchor_count=0,
                                    avg_pier_depth_ft=18, access_difficulty="EASY")
    cust = make_customer_headers(lead["id"])

    def _accept_new_job():
        quote = get_success_data(
            api_client.create_quote(
                create_quote_payload(lead["id"], scope["id"], "CASH"), SALES
            )
        )
        get_success_data(api_client.send_quote(quote["id"], SALES))
        get_success_data(api_client.accept_quote(quote["id"], cust))
        return fetch_job_for_quote(quote["id"])

    job1 = _accept_new_job()
    job2 = _accept_new_job()
    approve_permit_for_job(job1["id"])
    approve_permit_for_job(job2["id"])
    crew = create_crew(region_code="NORTH")
    job1 = get_success_data(
        api_client.schedule_job(
            job1["id"], schedule_job_payload(crew["id"], first_start, first_end), OPS
        )
    )
    return {"lead": lead, "crew": crew, "job1": job1, "job2": job2}


def setup_scheduled_job(*, scheduled_start: str = "2026-06-01T08:00:00Z",
                        scheduled_end: str = "2026-06-01T12:00:00Z", **kwargs) -> dict:
    """Job walked to SCHEDULED (permit approved, crew booked)."""
    ctx = setup_job_ready_to_schedule(**kwargs)
    ctx["job"] = get_success_data(
        api_client.schedule_job(
            ctx["job"]["id"],
            schedule_job_payload(ctx["crew"]["id"], scheduled_start, scheduled_end),
            OPS,
        )
    )
    return ctx


def setup_in_progress_job(**kwargs) -> dict:
    """Job walked to IN_PROGRESS (ready for complete)."""
    ctx = setup_scheduled_job(**kwargs)
    ctx["job"] = get_success_data(api_client.start_job(ctx["job"]["id"], OPS))
    return ctx


def setup_completed_install(*, piers_installed: int = 8, adjustment_inches: float = 1.0,
                            **kwargs) -> dict:
    """Full pipeline through install completion. Returns ctx with 'job' (COMPLETED),
    'warranty' (ACTIVE), and 'visit' (the auto-booked first MaintenanceVisit)."""
    ctx = setup_in_progress_job(**kwargs)
    ctx["job"] = get_success_data(
        api_client.complete_job(
            ctx["job"]["id"],
            complete_job_payload(piers_installed=piers_installed,
                                 adjustment_inches=adjustment_inches),
            OPS,
        )
    )
    warranties = get_success_data(
        api_client.list_warranties(OPS, params={"job_id": ctx["job"]["id"]})
    )
    ctx["warranty"] = warranties[0] if warranties else None
    if ctx["warranty"]:
        visits = get_success_data(
            api_client.list_visits(OPS, params={"warranty_id": ctx["warranty"]["id"]})
        )
        ctx["visit"] = visits[0] if visits else None
    return ctx


# ─── Tier 4: warranty / claim scenarios ──────────────────────────────────────

def setup_active_warranty(**kwargs) -> dict:
    """Alias for a completed install — yields an ACTIVE warranty. Returns full ctx."""
    return setup_completed_install(**kwargs)


def setup_claim_under_review(*, reported_settlement_inches: float = 1.0, **kwargs) -> dict:
    """ACTIVE warranty + a claim filed then moved to UNDER_REVIEW. Adds 'claim' to ctx."""
    ctx = setup_completed_install(**kwargs)
    lead = ctx["lead"]
    claim = get_success_data(
        api_client.create_claim(
            create_claim_payload(ctx["warranty"]["id"],
                                 reported_settlement_inches=reported_settlement_inches),
            make_customer_headers(lead["id"]),
        )
    )
    ctx["claim"] = get_success_data(api_client.review_claim(claim["id"], ADJUSTER))
    return ctx


def setup_missed_visit_claim_under_review(*, reported_settlement_inches: float = 1.5,
                                          missed_clock: str = "2027-06-01T00:00:00Z",
                                          **kwargs) -> dict:
    """ACTIVE warranty whose auto MaintenanceVisit (dated activated_at + 365 days =
    2027-05-01) has been marked MISSED, then a claim filed and moved to UNDER_REVIEW.

    Advances the logical clock past the visit date so mark-missed is legal (PRD §3.7),
    producing missed==1 so claim approval takes the PRORATED path (PRD §3.8).
    Adds 'claim' (UNDER_REVIEW) to ctx.
    """
    ctx = setup_completed_install(**kwargs)
    set_clock(missed_clock)
    get_success_data(api_client.mark_missed_visit(ctx["visit"]["id"], OPS))
    lead = ctx["lead"]
    claim = get_success_data(
        api_client.create_claim(
            create_claim_payload(ctx["warranty"]["id"],
                                 reported_settlement_inches=reported_settlement_inches),
            make_customer_headers(lead["id"]),
        )
    )
    ctx["claim"] = get_success_data(api_client.review_claim(claim["id"], ADJUSTER))
    return ctx


def setup_approved_claim(*, reported_settlement_inches: float = 1.0, **kwargs) -> dict:
    """A claim taken all the way to APPROVED (remediation job spawned, UNSCHEDULED).
    Adds 'claim' (APPROVED) and 'remediation_job' to ctx."""
    ctx = setup_claim_under_review(
        reported_settlement_inches=reported_settlement_inches, **kwargs
    )
    ctx["claim"] = get_success_data(api_client.approve_claim(ctx["claim"]["id"], ADJUSTER))
    rem_id = ctx["claim"].get("remediation_job_id")
    ctx["remediation_job"] = (
        get_success_data(api_client.get_job(rem_id, OPS)) if rem_id else None
    )
    return ctx
