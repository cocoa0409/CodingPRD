"""Weatherization API -- Flask entry point.

Implements the endpoint catalogue (PRD Section 4), the request-validation
precedence pipeline (PRD Section 2.5), the parallel job state dimensions and
cascades (PRD Section 2.8 / Section 3), optimistic concurrency for financing
offers (PRD Section 2.9), and the calculations in calc.py.

Storage is entirely in-memory (store.db). No entity is seeded at startup; the
process boots with an empty store on every invocation.
"""

import os
from datetime import timedelta

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import calc
from core import (
    ANY,
    ApiError,
    current_user_id,
    error_body,
    get_json_body,
    job_rebate_claims,
    job_scope_items,
    list_response,
    new_uuid,
    now_iso,
    parse_iso,
    recompute_crew,
    recompute_job_rollup,
    require_roles,
    resolve,
    resolve_fk,
    respond_object,
    serialize,
    touch,
    v_array,
    v_datetime,
    v_enum,
    v_int,
    v_num,
    v_str,
)
from store import db

app = Flask(__name__)
app.url_map.strict_slashes = False

PREFIX = "/weatherization"


# ---------------------------------------------------------------------------
# Entity constructors
# ---------------------------------------------------------------------------
def new_common_entity(fields):
    """Create an entity carrying the full common field set (PRD 2.4)."""
    ts = now_iso()
    entity = {
        "id": new_uuid(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    entity.update(fields)
    return entity


def new_test_entity(fields):
    """DiagnosticTest is immutable append-only: only id + created_at (PRD 2.4)."""
    entity = {
        "id": new_uuid(),
        "created_at": now_iso(),
        "_seq": db.next_seq(),
    }
    entity.update(fields)
    return entity


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify(error_body(err.error_id, err.message)), err.http_status


@app.errorhandler(HTTPException)
def handle_http_exception(err):
    if err.code == 404:
        return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404
    return jsonify(error_body("ERR_VALIDATION", err.description or "Bad request")), err.code


@app.errorhandler(Exception)
def handle_unexpected(err):
    return jsonify(error_body("ERR_INTERNAL", "Internal server error")), 500


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ===========================================================================
# Dwellings
# ===========================================================================
@app.route(PREFIX + "/dwellings", methods=["POST"])
@require_roles("ProgramAdmin")
def create_dwelling():
    body = get_json_body()
    fields = {
        "address": v_str(body, "address"),
        "year_built": v_int(body, "year_built"),
        "conditioned_area_sqft": v_num(body, "conditioned_area_sqft"),
        "foundation_type": v_enum(body, "foundation_type", {"SLAB", "CRAWLSPACE", "BASEMENT"}),
        "heating_fuel_type": v_enum(body, "heating_fuel_type", {"GAS", "ELECTRIC", "OIL", "PROPANE"}),
    }
    dwelling = new_common_entity(fields)
    db.dwellings[dwelling["id"]] = dwelling
    return respond_object(serialize(dwelling), 201)


@app.route(PREFIX + "/dwellings/<dwelling_id>", methods=["GET"])
@require_roles(ANY)
def get_dwelling(dwelling_id):
    dwelling = resolve(db.dwellings, dwelling_id)
    return respond_object(serialize(dwelling), 200)


# ===========================================================================
# WAP applications
# ===========================================================================
@app.route(PREFIX + "/wap-applications", methods=["POST"])
@require_roles("ProgramAdmin", "Homeowner")
def create_wap_application():
    body = get_json_body()
    dwelling_id = v_str(body, "dwelling_id")
    household_size = v_int(body, "household_size", minimum=1)
    income = v_int(body, "annual_gross_income_cents", minimum=0)
    resolve_fk(db.dwellings, dwelling_id)  # FK existence (404)

    income_limit = calc.wap_income_limit_cents(household_size)
    fields = {
        "dwelling_id": dwelling_id,
        "household_size": household_size,
        "annual_gross_income_cents": income,
        "income_limit_cents": income_limit,
        "status": calc.wap_status(income, income_limit),
    }
    wap = new_common_entity(fields)
    db.wap_applications[wap["id"]] = wap
    return respond_object(serialize(wap), 201)


@app.route(PREFIX + "/wap-applications/<wap_application_id>", methods=["GET"])
@require_roles(ANY)
def get_wap_application(wap_application_id):
    wap = resolve(db.wap_applications, wap_application_id)
    return respond_object(serialize(wap), 200)


@app.route(PREFIX + "/wap-applications", methods=["GET"])
@require_roles(ANY)
def list_wap_applications():
    return list_response(db.wap_applications, {"dwelling_id": "dwelling_id", "status": "status"})


# ===========================================================================
# Jobs
# ===========================================================================
@app.route(PREFIX + "/jobs", methods=["POST"])
@require_roles("ProgramAdmin")
def create_job():
    body = get_json_body()
    dwelling_id = v_str(body, "dwelling_id")
    program_track = v_enum(body, "program_track", {"WAP", "UTILITY", "MARKET"})
    cap = v_int(body, "rebate_budget_cap_cents", minimum=0)
    resolve_fk(db.dwellings, dwelling_id)  # FK existence (404)

    # Cross-entity precondition: WAP-track requires an ELIGIBLE application.
    if program_track == "WAP":
        eligible = any(
            w["dwelling_id"] == dwelling_id and w["status"] == "ELIGIBLE"
            for w in db.wap_applications.values()
        )
        if not eligible:
            raise ApiError("ERR_NOT_WAP_ELIGIBLE", "No ELIGIBLE WAP application for the dwelling")

    fields = {
        "dwelling_id": dwelling_id,
        "program_track": program_track,
        "rebate_budget_cap_cents": cap,
        "job_status": "ACTIVE",
        "install_status": "PLANNED",
        "verification_status": "PENDING",
        "total_estimated_cost_cents": 0,
        "approved_rebate_total_cents": 0,
        "tax_credit_cents": 0,
        "estimated_out_of_pocket_cents": 0,
        "estimated_annual_savings_kwh": 0.0,
        "verified_annual_savings_kwh": None,
    }
    job = new_common_entity(fields)
    db.jobs[job["id"]] = job
    return respond_object(serialize(job), 201)


@app.route(PREFIX + "/jobs/<job_id>", methods=["GET"])
@require_roles(ANY)
def get_job(job_id):
    job = resolve(db.jobs, job_id)
    return respond_object(serialize(job), 200)


@app.route(PREFIX + "/jobs", methods=["GET"])
@require_roles(ANY)
def list_jobs():
    return list_response(db.jobs, {"dwelling_id": "dwelling_id", "job_status": "job_status"})


@app.route(PREFIX + "/jobs/<job_id>/complete-install", methods=["POST"])
@require_roles("ProgramAdmin")
def complete_install(job_id):
    job = resolve(db.jobs, job_id)
    # State precondition (PRD 3.6): ACTIVE and install_status SCHEDULED.
    if job["job_status"] != "ACTIVE" or job["install_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Job must be ACTIVE with install_status SCHEDULED")
    # Structural: no APPROVED-but-uninstalled scope item may remain.
    if any(s["status"] == "APPROVED" for s in job_scope_items(job_id)):
        raise ApiError("ERR_SCOPE_INCOMPLETE", "An APPROVED-but-uninstalled scope item remains")

    job["install_status"] = "INSTALLED"
    recompute_job_rollup(job)
    touch(job, bump_version=True)  # completing install advances Job.version
    return respond_object(serialize(job), 200)


@app.route(PREFIX + "/jobs/<job_id>/verify", methods=["POST"])
@require_roles("Auditor")
def verify_job(job_id):
    body = get_json_body()
    post_test_id = v_str(body, "post_test_id")
    job = resolve(db.jobs, job_id)  # path existence (404)
    post = resolve_fk(db.diagnostic_tests, post_test_id)  # FK existence (404)

    # Resolve the baseline/post blower-door pair for this job (PRD 3.8).
    if not (post["kind"] == "BLOWER_DOOR" and post["stage"] == "POST" and post["job_id"] == job_id):
        raise ApiError("ERR_NOT_FOUND", "post_test_id is not a POST blower-door test of this job")
    baseline = db.diagnostic_tests.get(post.get("baseline_test_id"))
    if not baseline or not (
        baseline["kind"] == "BLOWER_DOOR"
        and baseline["stage"] == "BASELINE"
        and baseline["job_id"] == job_id
    ):
        raise ApiError("ERR_NOT_FOUND", "Referenced BASELINE blower-door test does not resolve")

    # State precondition: install_status must be INSTALLED.
    if job["install_status"] != "INSTALLED":
        raise ApiError("ERR_INVALID_STATE", "Job install_status must be INSTALLED")
    # Segregation of duties: verifier must differ from baseline tester.
    if current_user_id() == baseline.get("tester_user_id"):
        raise ApiError("ERR_SOD_VIOLATION", "Verifier recorded the baseline blower-door test")
    # Structural: at least one INSTALLED scope item.
    installed_scopes = [s for s in job_scope_items(job_id) if s["status"] == "INSTALLED"]
    if len(installed_scopes) < 1:
        raise ApiError("ERR_SCOPE_INCOMPLETE", "Verification requires >= 1 INSTALLED scope item")

    reduction = calc.cfm50_reduction(baseline["cfm_measured"], post["cfm_measured"])
    if reduction >= calc.MIN_REDUCTION_PCT:
        job["verification_status"] = "PASSED"
        job["verified_annual_savings_kwh"] = calc.verified_savings_kwh(
            baseline["cfm_measured"], post["cfm_measured"]
        )
        for s in installed_scopes:
            s["status"] = "VERIFIED"
            touch(s, bump_version=True)
        # Both parallel dimensions terminated favorably -> auto-complete.
        if job["install_status"] == "INSTALLED":
            job["job_status"] = "COMPLETED"
    else:
        job["verification_status"] = "FAILED"
        # Three-link cascade (PRD 3.8).
        for s in installed_scopes:
            s["status"] = "FAILED_VERIFICATION"  # link 1
            touch(s, bump_version=True)
            for c in job_rebate_claims(job_id):
                if c["scope_item_id"] == s["id"] and c["status"] == "APPROVED":
                    c["status"] = "VOIDED"  # link 2
                    touch(c, bump_version=True)
        recompute_job_rollup(job)  # link 3 (approved_rebate_total + out-of-pocket)

    touch(job, bump_version=True)  # running verification advances Job.version
    return respond_object(serialize(job), 200)


@app.route(PREFIX + "/jobs/<job_id>/cancel", methods=["POST"])
@require_roles("ProgramAdmin")
def cancel_job(job_id):
    job = resolve(db.jobs, job_id)
    if job["job_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE job may be cancelled")

    job["job_status"] = "CANCELLED"
    # Cascade: scope items in PROPOSED/APPROVED/INSTALLED -> CANCELLED, and each
    # such item's APPROVED rebate claim -> VOIDED.
    for s in job_scope_items(job_id):
        if s["status"] in ("PROPOSED", "APPROVED", "INSTALLED"):
            s["status"] = "CANCELLED"
            touch(s, bump_version=True)
            for c in job_rebate_claims(job_id):
                if c["scope_item_id"] == s["id"] and c["status"] == "APPROVED":
                    c["status"] = "VOIDED"
                    touch(c, bump_version=True)
    # Fan-out: SCHEDULED crew assignments -> CANCELLED, release crew-days.
    for a in db.crew_assignments.values():
        if a["job_id"] == job_id and a["status"] == "SCHEDULED":
            a["status"] = "CANCELLED"
            touch(a, bump_version=True)
            crew = db.crews.get(a["crew_id"])
            if crew:
                recompute_crew(crew)

    recompute_job_rollup(job)
    touch(job, bump_version=True)  # cancelling advances Job.version
    return respond_object(serialize(job), 200)


# ===========================================================================
# Energy audits
# ===========================================================================
@app.route(PREFIX + "/audits", methods=["POST"])
@require_roles("Auditor")
def create_audit():
    body = get_json_body()
    job_id = v_str(body, "job_id")
    resolve_fk(db.jobs, job_id)

    fields = {
        "job_id": job_id,
        "auditor_user_id": current_user_id(),
        "status": "DRAFT",
        "estimated_annual_savings_kwh": None,
    }
    audit = new_common_entity(fields)
    db.audits[audit["id"]] = audit
    return respond_object(serialize(audit), 201)


@app.route(PREFIX + "/audits/<audit_id>", methods=["GET"])
@require_roles(ANY)
def get_audit(audit_id):
    audit = resolve(db.audits, audit_id)
    return respond_object(serialize(audit), 200)


@app.route(PREFIX + "/audits", methods=["GET"])
@require_roles(ANY)
def list_audits():
    return list_response(db.audits, {"job_id": "job_id", "status": "status"})


@app.route(PREFIX + "/audits/<audit_id>/submit", methods=["POST"])
@require_roles("Auditor")
def submit_audit(audit_id):
    audit = resolve(db.audits, audit_id)
    if audit["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE", "Audit must be DRAFT or REJECTED to submit")

    # Sum estimated_savings_kwh over the job's non-REJECTED scope items.
    total = sum(
        s["estimated_savings_kwh"]
        for s in job_scope_items(audit["job_id"])
        if s["status"] != "REJECTED"
    )
    audit["estimated_annual_savings_kwh"] = calc.round_kwh(total)
    audit["status"] = "SUBMITTED"
    touch(audit, bump_version=True)
    return respond_object(serialize(audit), 200)


@app.route(PREFIX + "/audits/<audit_id>/decide", methods=["POST"])
@require_roles("ProgramAdmin")
def decide_audit(audit_id):
    body = get_json_body()
    decision = v_enum(body, "decision", {"APPROVE", "REJECT"})
    audit = resolve(db.audits, audit_id)
    if audit["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED audit may be decided")

    audit["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    touch(audit, bump_version=True)
    return respond_object(serialize(audit), 200)


# ===========================================================================
# Diagnostic tests
# ===========================================================================
@app.route(PREFIX + "/diagnostic-tests", methods=["POST"])
@require_roles("Auditor")
def create_diagnostic_test():
    body = get_json_body()
    job_id = v_str(body, "job_id")
    kind = v_enum(body, "kind", {"BLOWER_DOOR", "DUCT_LEAKAGE"})
    stage = v_enum(body, "stage", {"BASELINE", "POST"})
    cfm = v_num(body, "cfm_measured", exclusive_min=0)
    baseline_test_id = body.get("baseline_test_id")
    if baseline_test_id is not None and not isinstance(baseline_test_id, str):
        raise ApiError("ERR_VALIDATION", "baseline_test_id must be a string")

    resolve_fk(db.jobs, job_id)  # FK existence (404)
    if baseline_test_id is not None:
        resolve_fk(db.diagnostic_tests, baseline_test_id)  # FK existence (404)

    stored_baseline = None
    if stage == "POST":
        # Cross-entity: must reference a matching BASELINE test (same job & kind).
        ref = db.diagnostic_tests.get(baseline_test_id) if baseline_test_id else None
        if not ref or not (
            ref["stage"] == "BASELINE" and ref["kind"] == kind and ref["job_id"] == job_id
        ):
            raise ApiError("ERR_BASELINE_TEST_REQUIRED", "POST test needs a matching BASELINE test")
        stored_baseline = baseline_test_id

    fields = {
        "job_id": job_id,
        "kind": kind,
        "stage": stage,
        "cfm_measured": cfm,
        "baseline_test_id": stored_baseline,
        "tester_user_id": current_user_id(),
    }
    test = new_test_entity(fields)
    db.diagnostic_tests[test["id"]] = test
    return respond_object(serialize(test), 201)


@app.route(PREFIX + "/diagnostic-tests/<diagnostic_test_id>", methods=["GET"])
@require_roles(ANY)
def get_diagnostic_test(diagnostic_test_id):
    test = resolve(db.diagnostic_tests, diagnostic_test_id)
    return respond_object(serialize(test), 200)


@app.route(PREFIX + "/diagnostic-tests", methods=["GET"])
@require_roles(ANY)
def list_diagnostic_tests():
    return list_response(
        db.diagnostic_tests,
        {
            "job_id": "job_id",
            "baseline_test_id": "baseline_test_id",
            "kind": "kind",
            "stage": "stage",
        },
    )


# ===========================================================================
# Scope items
# ===========================================================================
@app.route(PREFIX + "/scope-items", methods=["POST"])
@require_roles("Auditor")
def create_scope_item():
    body = get_json_body()
    job_id = v_str(body, "job_id")
    audit_id = v_str(body, "audit_id")
    category = v_enum(
        body,
        "category",
        {"ATTIC_INSULATION", "WALL_INSULATION", "CRAWL_INSULATION", "AIR_SEALING", "DUCT_SEALING"},
    )
    area_sqft = v_num(body, "area_sqft", exclusive_min=0)
    target_r_value = v_num(body, "target_r_value", minimum=0)
    estimated_cost_cents = v_int(body, "estimated_cost_cents", minimum=0)
    estimated_savings_kwh = v_num(body, "estimated_savings_kwh", minimum=0)

    resolve_fk(db.jobs, job_id)
    resolve_fk(db.audits, audit_id)

    fields = {
        "job_id": job_id,
        "audit_id": audit_id,
        "category": category,
        "area_sqft": area_sqft,
        "target_r_value": target_r_value,
        "achieved_r_value": None,
        "estimated_cost_cents": estimated_cost_cents,
        "actual_cost_cents": None,
        "estimated_savings_kwh": estimated_savings_kwh,
        "status": "PROPOSED",
    }
    scope = new_common_entity(fields)
    db.scope_items[scope["id"]] = scope
    return respond_object(serialize(scope), 201)


@app.route(PREFIX + "/scope-items/<scope_item_id>", methods=["GET"])
@require_roles(ANY)
def get_scope_item(scope_item_id):
    scope = resolve(db.scope_items, scope_item_id)
    return respond_object(serialize(scope), 200)


@app.route(PREFIX + "/scope-items", methods=["GET"])
@require_roles(ANY)
def list_scope_items():
    return list_response(
        db.scope_items,
        {"job_id": "job_id", "audit_id": "audit_id", "status": "status", "category": "category"},
    )


@app.route(PREFIX + "/scope-items/<scope_item_id>/decide", methods=["POST"])
@require_roles("ProgramAdmin")
def decide_scope_item(scope_item_id):
    body = get_json_body()
    decision = v_enum(body, "decision", {"APPROVE", "REJECT"})
    scope = resolve(db.scope_items, scope_item_id)
    if scope["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", "Only a PROPOSED scope item may be decided")

    if decision == "APPROVE":
        audit = db.audits.get(scope["audit_id"])
        if not audit or audit["status"] != "APPROVED":
            raise ApiError("ERR_AUDIT_NOT_APPROVED", "Referenced audit is not APPROVED")
        scope["status"] = "APPROVED"
        touch(scope, bump_version=True)
        recompute_job_rollup(db.jobs[scope["job_id"]])
    else:
        scope["status"] = "REJECTED"
        touch(scope, bump_version=True)
    return respond_object(serialize(scope), 200)


@app.route(PREFIX + "/scope-items/<scope_item_id>/mark-installed", methods=["POST"])
@require_roles("Installer")
def mark_installed(scope_item_id):
    body = get_json_body()
    achieved_r_value = v_num(body, "achieved_r_value", minimum=0)
    actual_cost_cents = v_int(body, "actual_cost_cents", minimum=0)
    scope = resolve(db.scope_items, scope_item_id)

    if scope["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Scope item must be APPROVED to mark installed")
    job = db.jobs[scope["job_id"]]
    if job["install_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Referenced job install_status must be SCHEDULED")

    scope["achieved_r_value"] = achieved_r_value
    scope["actual_cost_cents"] = actual_cost_cents
    scope["status"] = "INSTALLED"
    touch(scope, bump_version=True)
    recompute_job_rollup(job)  # recomputes tax_credit_cents and financial rollup
    return respond_object(serialize(scope), 200)


# ===========================================================================
# Crews
# ===========================================================================
@app.route(PREFIX + "/crews", methods=["POST"])
@require_roles("ProgramAdmin")
def create_crew():
    body = get_json_body()
    name = v_str(body, "name")
    crew_size = v_int(body, "crew_size", minimum=1)
    skills = v_array(body, "skills")
    capacity_days = v_int(body, "capacity_days", minimum=0)

    fields = {
        "name": name,
        "crew_size": crew_size,
        "skills": skills,
        "capacity_days": capacity_days,
        "committed_days": 0,
        "available_days": capacity_days,
    }
    crew = new_common_entity(fields)
    db.crews[crew["id"]] = crew
    return respond_object(serialize(crew), 201)


@app.route(PREFIX + "/crews/<crew_id>", methods=["GET"])
@require_roles(ANY)
def get_crew(crew_id):
    crew = resolve(db.crews, crew_id)
    return respond_object(serialize(crew), 200)


# ===========================================================================
# Crew assignments
# ===========================================================================
def _windows_overlap(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


def _window_gap(s1, e1, s2, e2):
    if _windows_overlap(s1, e1, s2, e2):
        return timedelta(0)
    if e1 <= s2:
        return s2 - e1
    return s1 - e2


@app.route(PREFIX + "/crew-assignments", methods=["POST"])
@require_roles("ProgramAdmin")
def create_crew_assignment():
    body = get_json_body()
    job_id = v_str(body, "job_id")
    crew_id = v_str(body, "crew_id")
    start_dt = v_datetime(body, "scheduled_start_date")
    end_dt = v_datetime(body, "scheduled_end_date")

    job = resolve_fk(db.jobs, job_id)
    crew = resolve_fk(db.crews, crew_id)

    # Date-window validity (422).
    if not (end_dt > start_dt):
        raise ApiError("ERR_INVALID_DATE_WINDOW", "scheduled_end_date must be after scheduled_start_date")

    duration_days = (end_dt - start_dt).days

    # Structural constraints (in order): double-booking, dwelling conflict, capacity.
    for a in db.crew_assignments.values():
        if a["crew_id"] == crew_id and a["status"] == "SCHEDULED":
            if _windows_overlap(start_dt, end_dt, a["_start_dt"], a["_end_dt"]):
                raise ApiError("ERR_CREW_DOUBLE_BOOKED", "Crew already has an overlapping assignment")

    this_dwelling = job["dwelling_id"]
    for a in db.crew_assignments.values():
        if a["status"] != "SCHEDULED" or a["job_id"] == job_id:
            continue
        other_job = db.jobs.get(a["job_id"])
        if other_job and other_job["dwelling_id"] == this_dwelling:
            if _window_gap(start_dt, end_dt, a["_start_dt"], a["_end_dt"]) < timedelta(days=calc.BUFFER_DAYS):
                raise ApiError("ERR_DWELLING_WINDOW_CONFLICT", "Another job's window at the same dwelling is too close")

    if crew["committed_days"] + duration_days > crew["capacity_days"]:
        raise ApiError("ERR_CREW_CAPACITY_EXCEEDED", "Assignment would exceed crew capacity_days")

    fields = {
        "job_id": job_id,
        "crew_id": crew_id,
        "scheduled_start_date": body["scheduled_start_date"],
        "scheduled_end_date": body["scheduled_end_date"],
        "duration_days": duration_days,
        "status": "SCHEDULED",
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    }
    assignment = new_common_entity(fields)
    db.crew_assignments[assignment["id"]] = assignment
    recompute_crew(crew)  # reserve crew-days

    # First scheduled assignment moves install_status PLANNED -> SCHEDULED.
    if job["install_status"] == "PLANNED":
        job["install_status"] = "SCHEDULED"
        touch(job, bump_version=True)  # advances Job.version

    return respond_object(serialize(assignment), 201)


@app.route(PREFIX + "/crew-assignments/<crew_assignment_id>", methods=["GET"])
@require_roles(ANY)
def get_crew_assignment(crew_assignment_id):
    assignment = resolve(db.crew_assignments, crew_assignment_id)
    return respond_object(serialize(assignment), 200)


@app.route(PREFIX + "/crew-assignments", methods=["GET"])
@require_roles(ANY)
def list_crew_assignments():
    return list_response(
        db.crew_assignments,
        {"job_id": "job_id", "crew_id": "crew_id", "status": "status"},
    )


@app.route(PREFIX + "/crew-assignments/<crew_assignment_id>/cancel", methods=["POST"])
@require_roles("ProgramAdmin")
def cancel_crew_assignment(crew_assignment_id):
    assignment = resolve(db.crew_assignments, crew_assignment_id)
    if assignment["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED assignment may be cancelled")

    assignment["status"] = "CANCELLED"
    touch(assignment, bump_version=True)
    crew = db.crews.get(assignment["crew_id"])
    if crew:
        recompute_crew(crew)  # release crew-days
    return respond_object(serialize(assignment), 200)


# ===========================================================================
# Rebate claims
# ===========================================================================
@app.route(PREFIX + "/rebate-claims", methods=["POST"])
@require_roles("ProgramAdmin")
def create_rebate_claim():
    body = get_json_body()
    job_id = v_str(body, "job_id")
    scope_item_id = v_str(body, "scope_item_id")
    resolve_fk(db.jobs, job_id)
    scope = resolve_fk(db.scope_items, scope_item_id)

    provisional = calc.rebate_amount(scope["category"], scope["target_r_value"], scope["area_sqft"])
    fields = {
        "job_id": job_id,
        "scope_item_id": scope_item_id,
        "provisional_amount_cents": provisional,
        "finalized_amount_cents": None,
        "status": "DRAFT",
    }
    claim = new_common_entity(fields)
    db.rebate_claims[claim["id"]] = claim
    return respond_object(serialize(claim), 201)


@app.route(PREFIX + "/rebate-claims/<rebate_claim_id>", methods=["GET"])
@require_roles(ANY)
def get_rebate_claim(rebate_claim_id):
    claim = resolve(db.rebate_claims, rebate_claim_id)
    return respond_object(serialize(claim), 200)


@app.route(PREFIX + "/rebate-claims", methods=["GET"])
@require_roles(ANY)
def list_rebate_claims():
    return list_response(
        db.rebate_claims,
        {"job_id": "job_id", "scope_item_id": "scope_item_id", "status": "status"},
    )


@app.route(PREFIX + "/rebate-claims/<rebate_claim_id>/submit", methods=["POST"])
@require_roles("ProgramAdmin")
def submit_rebate_claim(rebate_claim_id):
    claim = resolve(db.rebate_claims, rebate_claim_id)
    if claim["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT claim may be submitted")
    scope = db.scope_items[claim["scope_item_id"]]
    if scope["status"] not in ("INSTALLED", "VERIFIED"):
        raise ApiError("ERR_SCOPE_NOT_INSTALLED", "Referenced scope item is not INSTALLED/VERIFIED")

    claim["finalized_amount_cents"] = calc.rebate_amount(
        scope["category"], scope["achieved_r_value"], scope["area_sqft"]
    )
    claim["status"] = "SUBMITTED"
    touch(claim, bump_version=True)
    return respond_object(serialize(claim), 200)


@app.route(PREFIX + "/rebate-claims/<rebate_claim_id>/decide", methods=["POST"])
@require_roles("ProgramAdmin")
def decide_rebate_claim(rebate_claim_id):
    body = get_json_body()
    decision = v_enum(body, "decision", {"APPROVE", "DENY"})
    claim = resolve(db.rebate_claims, rebate_claim_id)
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED claim may be decided")

    job = db.jobs[claim["job_id"]]
    if decision == "APPROVE":
        current = sum(
            (c["finalized_amount_cents"] or 0)
            for c in job_rebate_claims(job["id"])
            if c["status"] == "APPROVED"
        )
        if current + (claim["finalized_amount_cents"] or 0) > job["rebate_budget_cap_cents"]:
            raise ApiError("ERR_REBATE_BUDGET_EXCEEDED", "Approval would exceed the rebate budget cap")
        claim["status"] = "APPROVED"
        touch(claim, bump_version=True)
        recompute_job_rollup(job)
    else:
        claim["status"] = "DENIED"
        touch(claim, bump_version=True)
    return respond_object(serialize(claim), 200)


@app.route(PREFIX + "/rebate-claims/<rebate_claim_id>/void", methods=["POST"])
@require_roles("ProgramAdmin")
def void_rebate_claim(rebate_claim_id):
    claim = resolve(db.rebate_claims, rebate_claim_id)
    if claim["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED claim may be voided")

    claim["status"] = "VOIDED"
    touch(claim, bump_version=True)
    recompute_job_rollup(db.jobs[claim["job_id"]])
    return respond_object(serialize(claim), 200)


# ===========================================================================
# Financing plans
# ===========================================================================
@app.route(PREFIX + "/financing-plans", methods=["POST"])
@require_roles("ProgramAdmin", "Homeowner")
def create_financing_plan():
    body = get_json_body()
    job_id = v_str(body, "job_id")
    principal_cents = v_int(body, "principal_cents", exclusive_min=0)
    term_months = v_int(body, "term_months", minimum=1)
    apr_bps = v_int(body, "apr_bps", minimum=0)
    expected_job_version = v_int(body, "expected_job_version")
    job = resolve_fk(db.jobs, job_id)

    # Optimistic concurrency (412).
    if expected_job_version != job["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_job_version does not match the job version")

    # A newer offer supersedes any prior OFFERED plan for the same job.
    for plan in db.financing_plans.values():
        if plan["job_id"] == job_id and plan["status"] == "OFFERED":
            plan["status"] = "SUPERSEDED"
            touch(plan, bump_version=True)

    fields = {
        "job_id": job_id,
        "principal_cents": principal_cents,
        "term_months": term_months,
        "apr_bps": apr_bps,
        "monthly_payment_cents": calc.monthly_payment_cents(principal_cents, term_months, apr_bps),
        "status": "OFFERED",
    }
    plan = new_common_entity(fields)
    db.financing_plans[plan["id"]] = plan
    touch(job, bump_version=True)  # offering a plan advances Job.version
    return respond_object(serialize(plan), 201)


@app.route(PREFIX + "/financing-plans/<financing_plan_id>", methods=["GET"])
@require_roles(ANY)
def get_financing_plan(financing_plan_id):
    plan = resolve(db.financing_plans, financing_plan_id)
    return respond_object(serialize(plan), 200)


@app.route(PREFIX + "/financing-plans", methods=["GET"])
@require_roles(ANY)
def list_financing_plans():
    return list_response(db.financing_plans, {"job_id": "job_id", "status": "status"})


@app.route(PREFIX + "/financing-plans/<financing_plan_id>/respond", methods=["POST"])
@require_roles("Homeowner")
def respond_financing_plan(financing_plan_id):
    body = get_json_body()
    decision = v_enum(body, "decision", {"ACCEPT", "DECLINE"})
    plan = resolve(db.financing_plans, financing_plan_id)
    if plan["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", "Only an OFFERED plan may be responded to")

    plan["status"] = "ACCEPTED" if decision == "ACCEPT" else "DECLINED"
    touch(plan, bump_version=True)
    return respond_object(serialize(plan), 200)


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
