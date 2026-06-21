"""Composite setup helpers for the Roofing Storm Restoration API.

Most interesting claims require the Job to be deep in its lifecycle (CONTRACTED,
IN_PRODUCTION, COMPLETED), which takes 8-20 chained API calls to reach. These
helpers encapsulate those preambles so test functions focus on assertions.

The test harness restarts the server (empty DB) before every test, so every
helper builds its preconditions from scratch using only PRD-declared endpoints.
All setup calls use get_success_data() (lenient) so a setup failure surfaces as
a clear "Setup failed" rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_estimator_headers
from .factories import (
    create_estimator_payload, create_job_payload, create_crew_payload,
    create_inspection_payload, complete_inspection_payload,
    create_estimate_payload, create_line_item_payload,
    create_material_order_payload, deliver_material_order_payload,
    create_permit_payload, issue_permit_payload,
    create_draw_payload, create_change_order_payload, apply_change_order_payload,
    create_warranty_payload,
)

FA = TEST_USERS["field_adjuster_headers"]
PM = TEST_USERS["production_manager_headers"]
EST = TEST_USERS["estimator_headers"]

# Unique-permit-number counter so repeated issues within one test never collide.
_PERMIT_SEQ = [9000]


def _next_permit_number() -> str:
    _PERMIT_SEQ[0] += 1
    return f"P-{_PERMIT_SEQ[0]}"


# -----------------------------------------------------------------------------
# Atomic builders
# -----------------------------------------------------------------------------

def create_estimator(name="Ann Est", license_no="TX-1001") -> dict:
    """Create one Estimator (reference data). Returns the estimator resource."""
    resp = api_client.create_estimator(
        create_estimator_payload(name=name, license_no=license_no), EST)
    return get_success_data(resp)


def create_crew(name="Crew Alpha", **overrides) -> dict:
    """Create one Crew (reference data). Returns the crew resource."""
    resp = api_client.create_crew(create_crew_payload(name=name, **overrides), PM)
    return get_success_data(resp)


def create_lead_job(estimator_id=None, **job_overrides) -> dict:
    """Create an estimator (if not supplied) and a LEAD Job. Returns the job."""
    if estimator_id is None:
        estimator_id = create_estimator()["id"]
    resp = api_client.create_job(
        create_job_payload(assigned_estimator_id=estimator_id, **job_overrides), FA)
    return get_success_data(resp)


def pass_damage_assessment(job_id, severity="MODERATE",
                           start="2026-03-01T08:00:00Z", end="2026-03-01T10:00:00Z") -> dict:
    """Schedule + pass a DAMAGE_ASSESSMENT inspection for the job. Returns it."""
    resp = api_client.create_inspection(create_inspection_payload(
        job_id=job_id, kind="DAMAGE_ASSESSMENT",
        scheduled_start=start, scheduled_end=end), FA)
    insp = get_success_data(resp)
    api_client.complete_inspection(
        insp["id"], complete_inspection_payload(outcome="PASS", damage_severity=severity), FA)
    return insp


def add_finalized_field_estimate(job_id, line_items=None) -> dict:
    """Create a DRAFT FIELD estimate, append line items, finalize. Returns it.

    line_items defaults to a single SHINGLE 10sq @ 10000 waste 0.10 line,
    which produces final_total_cents == 110000.
    """
    if line_items is None:
        line_items = [{"trade": "SHINGLE", "squares": 10,
                       "unit_price_cents": 10_000, "waste_factor_pct": 0.10}]
    resp = api_client.create_estimate(
        create_estimate_payload(job_id=job_id, source_kind="FIELD"), EST)
    est = get_success_data(resp)
    for li in line_items:
        api_client.add_line_item(est["id"], create_line_item_payload(**li), EST)
    fin = api_client.finalize_estimate(est["id"], EST)
    return get_success_data(fin)


# -----------------------------------------------------------------------------
# Tier 1/2: State progression to milestones
# -----------------------------------------------------------------------------

def setup_estimated_job(line_items=None):
    """Walk a job to ESTIMATED with one FINALIZED FIELD estimate.

    Returns (job_id, estimate). The job is in ESTIMATED status; the estimate is
    FINALIZED (final_total_cents 110000 for the default single SHINGLE line).
    """
    estimator = create_estimator()
    job = create_lead_job(estimator_id=estimator["id"])
    pass_damage_assessment(job["id"])
    api_client.mark_job_inspected(job["id"], FA)
    est = add_finalized_field_estimate(job["id"], line_items=line_items)
    api_client.mark_job_estimated(job["id"], EST)
    return job["id"], est


def setup_contracted_job(line_items=None):
    """Walk a job to CONTRACTED, binding one FINALIZED FIELD estimate.

    Returns (job_id, estimate). contract_value_cents == estimate.final_total_cents
    (110000 by default).
    """
    job_id, est = setup_estimated_job(line_items=line_items)
    api_client.contract_job(job_id, {"estimate_id": est["id"]}, EST)
    return job_id, est


def setup_in_production_job(line_items=None, permit_number=None):
    """Walk a job all the way to IN_PRODUCTION.

    Returns (job_id, info) where info carries material_order, permit, estimate,
    and the current job version (job_version) just after start-production.
    """
    job_id, est = setup_contracted_job(line_items=line_items)
    mo = get_success_data(api_client.create_material_order(
        create_material_order_payload(job_id=job_id), PM))
    api_client.deliver_material_order(mo["id"], deliver_material_order_payload(), PM)
    permit = get_success_data(api_client.create_permit(
        create_permit_payload(job_id=job_id), PM))
    pn = permit_number or _next_permit_number()
    api_client.issue_permit(permit["id"], issue_permit_payload(permit_number=pn), PM)
    job = get_success_data(api_client.start_production(job_id, PM))
    info = {
        "estimate": est,
        "material_order": mo,
        "permit": permit,
        "job_version": job["version"],
        "job": job,
    }
    return job_id, info


# -----------------------------------------------------------------------------
# Tier 4: Draw / threshold targeting
# -----------------------------------------------------------------------------

def disburse_draw(job_id, cumulative_pct, expected_job_version):
    """Create (and atomically disburse) one draw. Returns the draw resource."""
    resp = api_client.create_draw(create_draw_payload(
        job_id=job_id, cumulative_pct=cumulative_pct,
        expected_job_version=expected_job_version), PM)
    return get_success_data(resp)


def current_job_version(job_id) -> int:
    """Re-read the live Job.version (used to thread OCC tokens)."""
    job = get_success_data(api_client.get_job(job_id, PM))
    return job["version"]


def setup_in_production_with_draw(cumulative_pct=0.5, line_items=None):
    """IN_PRODUCTION job with one DISBURSED draw at cumulative_pct.

    Returns (job_id, info) where info adds 'draw' and 'job_version' (re-read
    after the draw, i.e. the fresh OCC token for the next ledger write).
    """
    job_id, info = setup_in_production_job(line_items=line_items)
    draw = disburse_draw(job_id, cumulative_pct, info["job_version"])
    info["draw"] = draw
    info["job_version"] = current_job_version(job_id)
    return job_id, info


# -----------------------------------------------------------------------------
# Tier 3: Change-order lifecycle shortcuts
# -----------------------------------------------------------------------------

def setup_approved_change_order(job_id, delta_cents=50_000, extra_shingle_squares=None):
    """Propose + approve a change order on an existing job. Returns the CO."""
    payload = create_change_order_payload(
        job_id=job_id, reason="scope change", delta_cents=delta_cents)
    if extra_shingle_squares is not None:
        payload["extra_shingle_squares"] = extra_shingle_squares
    co = get_success_data(api_client.create_change_order(payload, PM))
    co = get_success_data(api_client.approve_change_order(co["id"], PM))
    return co


def apply_change_order(change_order_id, job_id):
    """Apply an APPROVED change order using the current Job.version. Returns CO."""
    jv = current_job_version(job_id)
    resp = api_client.apply_change_order(
        change_order_id, apply_change_order_payload(expected_job_version=jv), PM)
    return get_success_data(resp)


# -----------------------------------------------------------------------------
# Tier 5: Finalization / terminal-state and warranty
# -----------------------------------------------------------------------------

def setup_completed_job(line_items=None, permit_number=None,
                        permit_final_start="2026-07-10T08:00:00Z",
                        permit_final_end="2026-07-10T12:00:00Z"):
    """Drive a job all the way to COMPLETED.

    Bills to 100% via a single final draw, passes a PERMIT_FINAL inspection,
    then completes. Returns (job_id, info) with material_order, permit, estimate,
    permit_final inspection, and the post-complete job snapshot.
    """
    job_id, info = setup_in_production_job(line_items=line_items, permit_number=permit_number)
    # Final draw -> billed_pct == 1.0
    disburse_draw(job_id, 1.0, info["job_version"])
    # PERMIT_FINAL inspection -> PASSED (also closes the issued permit)
    pf = get_success_data(api_client.create_inspection(create_inspection_payload(
        job_id=job_id, kind="PERMIT_FINAL", permit_id=info["permit"]["id"],
        scheduled_start=permit_final_start, scheduled_end=permit_final_end), FA))
    api_client.complete_inspection(pf["id"], complete_inspection_payload(outcome="PASS"), FA)
    job = get_success_data(api_client.complete_job(job_id, PM))
    info["permit_final"] = pf
    info["job"] = job
    info["job_version"] = job["version"]
    return job_id, info


def setup_active_warranty(premium_cents=120_000, term_months=120,
                          start_clock="2026-01-01T00:00:00Z",
                          line_items=None):
    """Create a COMPLETED job, then a PENDING warranty, activate it.

    Sets the logical clock to start_clock BEFORE activation so start_at is
    deterministic. Returns (job_id, warranty, info).
    """
    api_client.set_clock({"to_iso8601": start_clock}, PM)
    job_id, info = setup_completed_job(line_items=line_items)
    war = get_success_data(api_client.create_warranty(create_warranty_payload(
        job_id=job_id, premium_cents=premium_cents, term_months=term_months), PM))
    war = get_success_data(api_client.activate_warranty(war["id"], PM))
    info["warranty"] = war
    return job_id, war, info


def set_clock(to_iso8601: str):
    """Set the server logical clock (PRD §2.4)."""
    return api_client.set_clock({"to_iso8601": to_iso8601}, PM)
