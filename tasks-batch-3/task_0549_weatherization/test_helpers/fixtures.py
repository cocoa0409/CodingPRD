"""Composite setup helpers for multi-step test prerequisites.

Every test runs against a freshly-restarted (empty) server, so each fixture
builds its entire precondition state from scratch using only PRD-declared
endpoints. Setup calls use ``get_success_data()`` (lenient) so a broken preamble
surfaces as a clear "setup failed" rather than a confusing assertion failure.

All roles are opaque; auditor user-ids are threaded explicitly where a workflow
records and later compares them (baseline tester vs verifying auditor -> SOD).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_dwelling_payload,
    create_wap_application_payload,
    create_job_payload,
    create_audit_payload,
    create_scope_item_payload,
    create_diagnostic_test_payload,
    create_crew_payload,
    create_crew_assignment_payload,
    create_rebate_claim_payload,
    create_financing_plan_payload,
)
from .test_users import TEST_USERS, make_auditor_headers, make_installer_headers

ADMIN = TEST_USERS["program_admin_headers"]
INSTALLER = TEST_USERS["installer_headers"]
HOMEOWNER = TEST_USERS["homeowner_headers"]

DEFAULT_START = "2026-06-01T00:00:00Z"
DEFAULT_END = "2026-06-05T00:00:00Z"


# ─── Step helpers ─────────────────────────────────────────────────────────
def new_dwelling(**over):
    return get_success_data(api_client.create_dwelling(create_dwelling_payload(**over), ADMIN))


def new_wap_application(dwelling_id, **over):
    return get_success_data(
        api_client.create_wap_application(create_wap_application_payload(dwelling_id, **over), HOMEOWNER)
    )


def new_job(dwelling_id, **over):
    return get_success_data(api_client.create_job(create_job_payload(dwelling_id, **over), ADMIN))


def new_audit(job_id, auditor_user_id="auditor-alice"):
    return get_success_data(
        api_client.create_audit(create_audit_payload(job_id), make_auditor_headers(auditor_user_id))
    )


def new_scope(job_id, audit_id, auditor_user_id="auditor-alice", **over):
    return get_success_data(
        api_client.create_scope_item(
            create_scope_item_payload(job_id, audit_id, **over), make_auditor_headers(auditor_user_id)
        )
    )


def submit_audit(audit_id, auditor_user_id="auditor-alice"):
    return get_success_data(api_client.submit_audit(audit_id, make_auditor_headers(auditor_user_id)))


def decide_audit(audit_id, decision):
    return get_success_data(api_client.decide_audit(audit_id, {"decision": decision}, ADMIN))


def decide_scope(scope_id, decision):
    return get_success_data(api_client.decide_scope_item(scope_id, {"decision": decision}, ADMIN))


def new_crew(**over):
    return get_success_data(api_client.create_crew(create_crew_payload(**over), ADMIN))


def new_assignment(job_id, crew_id, start=DEFAULT_START, end=DEFAULT_END):
    return get_success_data(
        api_client.create_crew_assignment(
            create_crew_assignment_payload(job_id, crew_id, scheduled_start_date=start, scheduled_end_date=end),
            ADMIN,
        )
    )


def install_scope(scope_id, achieved_r, actual_cost):
    return get_success_data(
        api_client.mark_installed(
            scope_id, {"achieved_r_value": achieved_r, "actual_cost_cents": actual_cost}, INSTALLER
        )
    )


def do_complete_install(job_id):
    return get_success_data(api_client.complete_install(job_id, ADMIN))


def new_diagnostic(job_id, kind, stage, cfm, baseline_id=None, tester_user_id="auditor-alice"):
    over = {"kind": kind, "stage": stage, "cfm_measured": cfm}
    if baseline_id is not None:
        over["baseline_test_id"] = baseline_id
    return get_success_data(
        api_client.create_diagnostic_test(
            create_diagnostic_test_payload(job_id, **over), make_auditor_headers(tester_user_id)
        )
    )


def new_rebate(job_id, scope_id):
    return get_success_data(
        api_client.create_rebate_claim(create_rebate_claim_payload(job_id, scope_id), ADMIN)
    )


def do_submit_rebate(rebate_id):
    return get_success_data(api_client.submit_rebate_claim(rebate_id, ADMIN))


def decide_rebate(rebate_id, decision):
    return get_success_data(api_client.decide_rebate_claim(rebate_id, {"decision": decision}, ADMIN))


def do_void_rebate(rebate_id):
    return get_success_data(api_client.void_rebate_claim(rebate_id, ADMIN))


def read_job(job_id):
    return get_success_data(api_client.get_job(job_id, ADMIN))


def new_financing(job_id, expected_job_version, **over):
    return get_success_data(
        api_client.create_financing_plan(create_financing_plan_payload(job_id, expected_job_version, **over), ADMIN)
    )


# ─── Composite: installed attic (or other) scope ─────────────────────────
def setup_installed_scope(
    *,
    cap=300_000,
    category="ATTIC_INSULATION",
    area=1000,
    target_r=38,
    achieved_r=38,
    estimated_cost=300_000,
    actual_cost=300_000,
    estimated_savings=1000,
    auditor_user_id="auditor-alice",
    crew_capacity=30,
):
    """Job with one APPROVED-then-INSTALLED scope; install_status is SCHEDULED
    (crew scheduled), scope status is INSTALLED. Returns handles dict.

    Chain: dwelling -> job -> audit -> scope -> submit -> approve audit ->
    approve scope -> crew -> assignment -> mark-installed.
    """
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], program_track="UTILITY", rebate_budget_cap_cents=cap)
    audit = new_audit(job["id"], auditor_user_id=auditor_user_id)
    scope = new_scope(
        job["id"],
        audit["id"],
        auditor_user_id=auditor_user_id,
        category=category,
        area_sqft=area,
        target_r_value=target_r,
        estimated_cost_cents=estimated_cost,
        estimated_savings_kwh=estimated_savings,
    )
    submit_audit(audit["id"], auditor_user_id=auditor_user_id)
    decide_audit(audit["id"], "APPROVE")
    decide_scope(scope["id"], "APPROVE")
    crew = new_crew(name="Fixture Crew", skills=[category], capacity_days=crew_capacity)
    assignment = new_assignment(job["id"], crew["id"])
    install_scope(scope["id"], achieved_r, actual_cost)
    return {
        "dwelling": dwelling,
        "job": read_job(job["id"]),
        "audit": audit,
        "scope": get_success_data(api_client.get_scope_item(scope["id"], ADMIN)),
        "crew": crew,
        "assignment": assignment,
    }


def setup_completed_install(**kw):
    """setup_installed_scope + complete-install (install_status -> INSTALLED)."""
    ctx = setup_installed_scope(**kw)
    do_complete_install(ctx["job"]["id"])
    ctx["job"] = read_job(ctx["job"]["id"])
    return ctx


def setup_verify_ready(
    *,
    baseline_cfm=3000,
    post_cfm=2400,
    post_tester="auditor-bob",
    with_approved_rebate=False,
    **kw,
):
    """Job installed + complete + a BASELINE/POST blower-door pair, ready to
    verify. The audit/scope/baseline auditor defaults to ``auditor-alice`` (kw
    ``auditor_user_id``); the POST tester defaults to ``auditor-bob`` so a verify
    by ``auditor-bob`` satisfies segregation of duties.

    When ``with_approved_rebate`` is set, a rebate is created, submitted, and
    approved before verification (so its budget is on the ledger to be unwound).
    """
    baseline_tester = kw.get("auditor_user_id", "auditor-alice")
    ctx = setup_completed_install(**kw)
    job_id = ctx["job"]["id"]
    if with_approved_rebate:
        rebate = new_rebate(job_id, ctx["scope"]["id"])
        do_submit_rebate(rebate["id"])
        decide_rebate(rebate["id"], "APPROVE")
        ctx["rebate"] = get_success_data(api_client.get_rebate_claim(rebate["id"], ADMIN))
    base = new_diagnostic(job_id, "BLOWER_DOOR", "BASELINE", baseline_cfm, tester_user_id=baseline_tester)
    post = new_diagnostic(
        job_id, "BLOWER_DOOR", "POST", post_cfm, baseline_id=base["id"], tester_user_id=post_tester
    )
    ctx["base_test_id"] = base["id"]
    ctx["post_test_id"] = post["id"]
    ctx["baseline_tester"] = baseline_tester
    ctx["post_tester"] = post_tester
    ctx["job"] = read_job(job_id)
    return ctx


def setup_verify_ready_no_scope(
    *, baseline_cfm=3000, post_cfm=2400, baseline_tester="auditor-alice", post_tester="auditor-bob"
):
    """Job with install_status INSTALLED but ZERO scope items, plus a
    BASELINE/POST blower-door pair. Used for the SOD-vs-scope-incomplete and
    empty-installed-set verify scenarios."""
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], program_track="UTILITY", rebate_budget_cap_cents=100_000)
    crew = new_crew(name="No-Scope Crew", skills=["AIR_SEALING"], capacity_days=20)
    new_assignment(job["id"], crew["id"], start=DEFAULT_START, end="2026-06-03T00:00:00Z")
    do_complete_install(job["id"])
    base = new_diagnostic(job["id"], "BLOWER_DOOR", "BASELINE", baseline_cfm, tester_user_id=baseline_tester)
    post = new_diagnostic(
        job["id"], "BLOWER_DOOR", "POST", post_cfm, baseline_id=base["id"], tester_user_id=post_tester
    )
    return {
        "job": read_job(job["id"]),
        "base_test_id": base["id"],
        "post_test_id": post["id"],
        "baseline_tester": baseline_tester,
        "post_tester": post_tester,
    }


# ─── Composite: rebate claim states ──────────────────────────────────────
def setup_rebate_draft(*, target_r=38, achieved_r=25, actual_cost=320_000, **kw):
    """Installed scope + a DRAFT rebate claim (provisional computed from
    target_r; finalized still null). Returns {job, scope, rebate}."""
    ctx = setup_installed_scope(target_r=target_r, achieved_r=achieved_r, actual_cost=actual_cost, **kw)
    rebate = new_rebate(ctx["job"]["id"], ctx["scope"]["id"])
    return {"job": read_job(ctx["job"]["id"]), "scope": ctx["scope"], "rebate": rebate}


def setup_rebate_submitted(*, cap=300_000, target_r=38, achieved_r=38, actual_cost=300_000, estimated_cost=300_000, area=1000, category="ATTIC_INSULATION", estimated_savings=500):
    """Installed scope + rebate created and SUBMITTED (finalized computed from
    achieved_r). Returns {job, scope, rebate}."""
    ctx = setup_installed_scope(
        cap=cap,
        category=category,
        area=area,
        target_r=target_r,
        achieved_r=achieved_r,
        estimated_cost=estimated_cost,
        actual_cost=actual_cost,
        estimated_savings=estimated_savings,
    )
    rebate = new_rebate(ctx["job"]["id"], ctx["scope"]["id"])
    do_submit_rebate(rebate["id"])
    return {
        "job": read_job(ctx["job"]["id"]),
        "scope": ctx["scope"],
        "rebate": get_success_data(api_client.get_rebate_claim(rebate["id"], ADMIN)),
    }


def setup_rebate_approved(**kw):
    """setup_rebate_submitted + decide APPROVE. Returns {job, scope, rebate}."""
    ctx = setup_rebate_submitted(**kw)
    decide_rebate(ctx["rebate"]["id"], "APPROVE")
    return {
        "job": read_job(ctx["job"]["id"]),
        "scope": ctx["scope"],
        "rebate": get_success_data(api_client.get_rebate_claim(ctx["rebate"]["id"], ADMIN)),
    }


def setup_rebate_denied(**kw):
    """setup_rebate_submitted + decide DENY. Returns {job, scope, rebate}."""
    ctx = setup_rebate_submitted(**kw)
    decide_rebate(ctx["rebate"]["id"], "DENY")
    return {
        "job": read_job(ctx["job"]["id"]),
        "scope": ctx["scope"],
        "rebate": get_success_data(api_client.get_rebate_claim(ctx["rebate"]["id"], ADMIN)),
    }


# ─── Composite: audit / scope early states ───────────────────────────────
def setup_proposed_scope_submitted_audit():
    """Submitted-but-not-decided audit with one PROPOSED scope item."""
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    audit = new_audit(job["id"])
    scope = new_scope(
        job["id"],
        audit["id"],
        category="CRAWL_INSULATION",
        area_sqft=900,
        target_r_value=19,
        estimated_cost_cents=80_000,
        estimated_savings_kwh=300,
    )
    submit_audit(audit["id"])
    return {"job": job, "audit": audit, "scope": scope}


def setup_draft_rebate_on_approved_scope():
    """An APPROVED (not-yet-installed) scope item with a DRAFT rebate claim."""
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    audit = new_audit(job["id"])
    scope = new_scope(
        job["id"], audit["id"], category="ATTIC_INSULATION", area_sqft=1000, target_r_value=38,
        estimated_cost_cents=120_000, estimated_savings_kwh=600,
    )
    submit_audit(audit["id"])
    decide_audit(audit["id"], "APPROVE")
    decide_scope(scope["id"], "APPROVE")
    rebate = new_rebate(job["id"], scope["id"])
    return {"job": job, "scope": scope, "rebate": rebate}


# ─── Composite: crew scheduling preconditions ────────────────────────────
def setup_crew_double_booked_precondition():
    """One crew already SCHEDULED to job A over 2026-06-01..2026-06-10 (9 days);
    a second job B at a DIFFERENT dwelling awaits scheduling. Returns
    {crew, job_b}."""
    dwelling_a = new_dwelling(address="15 Linden St")
    dwelling_b = new_dwelling(address="16 Sycamore St")
    job_a = new_job(dwelling_a["id"], rebate_budget_cap_cents=100_000)
    job_b = new_job(dwelling_b["id"], rebate_budget_cap_cents=100_000)
    crew = new_crew(name="Crew J", crew_size=3, skills=["ATTIC_INSULATION"], capacity_days=60)
    new_assignment(job_a["id"], crew["id"], start="2026-06-01T00:00:00Z", end="2026-06-10T00:00:00Z")
    return {"crew": crew, "job_b": job_b}


def setup_dwelling_window_precondition():
    """One dwelling, two jobs, two crews; crew1 SCHEDULED to job A over
    2026-06-01..2026-06-05. Returns {crew1, crew2, job_a, job_b, dwelling}."""
    dwelling = new_dwelling(address="17 Chestnut St")
    job_a = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    job_b = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    crew1 = new_crew(name="Crew K", crew_size=3, skills=["ATTIC_INSULATION"], capacity_days=30)
    crew2 = new_crew(name="Crew L", crew_size=3, skills=["ATTIC_INSULATION"], capacity_days=30)
    new_assignment(job_a["id"], crew1["id"], start="2026-06-01T00:00:00Z", end="2026-06-05T00:00:00Z")
    return {"crew1": crew1, "crew2": crew2, "job_a": job_a, "job_b": job_b, "dwelling": dwelling}


def setup_scheduled_assignment(*, capacity_days=20, start=DEFAULT_START, end=DEFAULT_END):
    """A crew with one SCHEDULED assignment. Returns {crew, assignment, job}."""
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    crew = new_crew(name="Crew M", crew_size=3, skills=["ATTIC_INSULATION"], capacity_days=capacity_days)
    assignment = new_assignment(job["id"], crew["id"], start=start, end=end)
    return {"crew": crew, "assignment": assignment, "job": job}


# ─── Composite: financing preconditions ──────────────────────────────────
def setup_financing_offered(*, principal=500_000, term=60, apr=600):
    """A job with one OFFERED financing plan already created. Returns
    {job, financing, job_after} where job_after reflects the post-supersede
    (incremented) version."""
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    financing = new_financing(
        job["id"], job["version"], principal_cents=principal, term_months=term, apr_bps=apr
    )
    return {"job": job, "financing": financing, "job_after": read_job(job["id"])}


def setup_job_cancel_cascade_ready():
    """ACTIVE job with an INSTALLED attic scope, a SCHEDULED crew assignment, and
    an APPROVED rebate (finalized 90000 on the ledger). No complete-install, no
    verification. Returns {job, scope, rebate, assignment}."""
    dwelling = new_dwelling(address="8 Maple St")
    job = new_job(dwelling["id"], rebate_budget_cap_cents=300_000)
    audit = new_audit(job["id"])
    scope = new_scope(
        job["id"], audit["id"], category="ATTIC_INSULATION", area_sqft=1000, target_r_value=30,
        estimated_cost_cents=100_000, estimated_savings_kwh=700,
    )
    submit_audit(audit["id"])
    decide_audit(audit["id"], "APPROVE")
    decide_scope(scope["id"], "APPROVE")
    crew = new_crew(name="Crew F", crew_size=3, skills=["ATTIC_INSULATION"], capacity_days=20)
    assignment = new_assignment(job["id"], crew["id"], start=DEFAULT_START, end="2026-06-04T00:00:00Z")
    install_scope(scope["id"], 30, 100_000)
    rebate = new_rebate(job["id"], scope["id"])
    do_submit_rebate(rebate["id"])
    decide_rebate(rebate["id"], "APPROVE")
    return {
        "job": read_job(job["id"]),
        "scope": scope,
        "rebate": get_success_data(api_client.get_rebate_claim(rebate["id"], ADMIN)),
        "assignment": assignment,
    }


def setup_two_attic_scopes_first_installed(*, actual_cost=33_500):
    """Job with two APPROVED attic scope items; the FIRST already INSTALLED at
    ``actual_cost``, the second still APPROVED (ready to mark-installed).
    Returns {job, scope1, scope2}."""
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], rebate_budget_cap_cents=300_000)
    audit = new_audit(job["id"])
    scope1 = new_scope(
        job["id"], audit["id"], category="ATTIC_INSULATION", area_sqft=1000, target_r_value=30,
        estimated_cost_cents=100_000, estimated_savings_kwh=500,
    )
    scope2 = new_scope(
        job["id"], audit["id"], category="ATTIC_INSULATION", area_sqft=1000, target_r_value=30,
        estimated_cost_cents=100_000, estimated_savings_kwh=500,
    )
    submit_audit(audit["id"])
    decide_audit(audit["id"], "APPROVE")
    decide_scope(scope1["id"], "APPROVE")
    decide_scope(scope2["id"], "APPROVE")
    crew = new_crew(name="Crew C", crew_size=4, skills=["ATTIC_INSULATION"], capacity_days=30)
    new_assignment(job["id"], crew["id"], start=DEFAULT_START, end="2026-06-06T00:00:00Z")
    install_scope(scope1["id"], 30, actual_cost)
    return {"job": read_job(job["id"]), "scope1": scope1, "scope2": scope2}
