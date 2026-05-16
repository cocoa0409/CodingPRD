"""Application routes (PRD §3.3)."""

from flask import Blueprint, g, request

from core.auth import require_roles
from core.clock import CLOCK
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, gen_id, lock
from core.timeutils import iso_format, days
from core.validation import require_body, require_field, require_enum, optional_enum
from services.mutations import stamp_create, bump
from services.projections import (
    project_application,
    project_determination,
    project_enrollment,
    find_policy_by_state,
    list_applicants_of_household,
)
from services.snapshot import compute_snapshots, check_application_eligibility
from services.calculations import effective_household_size


bp = Blueprint("applications", __name__)


_PROGRAMS = {"MAGI_ADULT", "MAGI_CHILD", "MAGI_PREGNANT", "NON_MAGI_DISABILITY", "NON_MAGI_AGED"}
_RULE_VARIANTS = {"FEDERAL", "STATE"}
_INELIGIBILITY_REASONS = {
    "INCOME_EXCEEDS_LIMIT", "ASSETS_EXCEED_LIMIT",
    "NOT_RESIDENT", "NON_QUALIFYING_PROGRAM",
}


def _resolve_household_application(household_id, application_id):
    household = STORE.households.get(household_id)
    if household is None:
        raise_error("ERR_NOT_FOUND", "Household not found")
    app = STORE.applications.get(application_id)
    if app is None or app["household_id"] != household_id:
        raise_error("ERR_NOT_FOUND", "Application not found")
    return household, app


@bp.route("/households/<household_id>/applications", methods=["POST"])
@require_roles("IntakeWorker")
def create_application(household_id):
    household = STORE.households.get(household_id)
    if household is None:
        raise_error("ERR_NOT_FOUND", "Household not found")
    body = require_body(request)
    program = require_enum(body, "program", _PROGRAMS)
    rule_variant = optional_enum(body, "rule_variant", _RULE_VARIANTS, default="STATE")

    with lock():
        aid = gen_id()
        row = {
            "id": aid,
            "household_id": household_id,
            "program": program,
            "rule_variant": rule_variant,
            "submitted_at": None,
            "status": "DRAFT",
            "snapshot_magi": None,
            "snapshot_fpl_percent": None,
            "snapshot_countable_assets": None,
        }
        stamp_create(row)
        STORE.applications[aid] = row
    return success_object(project_application(row), status=201)


@bp.route("/households/<household_id>/applications/<application_id>", methods=["GET"])
@require_roles("IntakeWorker", "EligibilityCaseworker", "AppealsOfficer")
def get_application(household_id, application_id):
    _, app = _resolve_household_application(household_id, application_id)
    return success_object(project_application(app))


@bp.route("/households/<household_id>/applications/<application_id>", methods=["PATCH"])
@require_roles("IntakeWorker")
def patch_application(household_id, application_id):
    _, app = _resolve_household_application(household_id, application_id)
    body = require_body(request)
    if app["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE", "Application must be DRAFT to patch")
    if "version" in body and body["version"] is not None:
        v = body["version"]
        if not isinstance(v, int) or isinstance(v, bool):
            raise_error("ERR_INVALID_REQUEST", "version must be an integer")
        if v != app["version"]:
            raise_error("ERR_VERSION_CONFLICT", "version does not match")
    changed = False
    if "rule_variant" in body and body["rule_variant"] is not None:
        rv = body["rule_variant"]
        if rv not in _RULE_VARIANTS:
            raise_error("ERR_INVALID_REQUEST", "rule_variant invalid")
        app["rule_variant"] = rv
        changed = True
    if "program" in body and body["program"] is not None:
        pg = body["program"]
        if pg not in _PROGRAMS:
            raise_error("ERR_INVALID_REQUEST", "program invalid")
        app["program"] = pg
        changed = True
    if changed:
        bump(app)
    return success_object(project_application(app))


@bp.route("/households/<household_id>/applications/<application_id>/submit", methods=["POST"])
@require_roles("IntakeWorker")
def submit_application(household_id, application_id):
    household, app = _resolve_household_application(household_id, application_id)
    if app["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE", "Application must be DRAFT to submit")
    # Household completeness check (priority 6 before FPL threshold check)
    policy = find_policy_by_state(household["state_code"])
    if policy is None:
        raise_error("ERR_HOUSEHOLD_INCOMPLETE", "Household state_code has no StatePolicy")
    if not household.get("head_applicant_id"):
        raise_error("ERR_HOUSEHOLD_INCOMPLETE", "Household has no head_applicant_id set")
    applicants = list_applicants_of_household(household_id)
    if not any(a["dependent_status"] != "EXCLUDED" for a in applicants):
        raise_error("ERR_HOUSEHOLD_INCOMPLETE", "Household has no non-EXCLUDED applicant")
    # FPL threshold check (priority 13)
    eff_size = effective_household_size(applicants)
    if eff_size <= 0:
        raise_error("ERR_FPL_THRESHOLD_INVALID", "Effective household size is zero")
    # Compute snapshots
    snap_magi, snap_fpl, snap_assets, _ = compute_snapshots(household, app["rule_variant"])
    with lock():
        app["snapshot_magi"] = snap_magi
        app["snapshot_fpl_percent"] = snap_fpl
        app["snapshot_countable_assets"] = snap_assets
        app["submitted_at"] = CLOCK.now_iso()
        app["status"] = "UNDER_REVIEW"
        bump(app)
    return success_object(project_application(app))


def _check_enrollment_overlaps(applicant_id, new_start_dt, new_end_dt):
    """Half-open overlap check on the same applicant against existing
    Enrollments in ACTIVE / CONTINUOUS_COVERAGE / REDETERMINATION_DUE."""
    from core.timeutils import parse_iso
    for e in STORE.enrollments.values():
        if e["applicant_id"] != applicant_id:
            continue
        if e["coverage_status"] not in ("ACTIVE", "CONTINUOUS_COVERAGE", "REDETERMINATION_DUE"):
            continue
        try:
            existing_start = parse_iso(e["coverage_start"], "coverage_start")
            existing_end = parse_iso(e["coverage_end"], "coverage_end")
        except Exception:
            continue
        # Half-open [s, e): overlap iff new_start < existing_end AND existing_start < new_end
        if new_start_dt < existing_end and existing_start < new_end_dt:
            return True
    return False


@bp.route("/households/<household_id>/applications/<application_id>/decide", methods=["POST"])
@require_roles("EligibilityCaseworker")
def decide_application(household_id, application_id):
    household, app = _resolve_household_application(household_id, application_id)
    if app["status"] != "UNDER_REVIEW":
        raise_error("ERR_INVALID_STATE", "Application must be UNDER_REVIEW to decide")
    body = require_body(request)
    decision = require_enum(body, "decision", {"APPROVE", "DENY"})
    ineligibility_reason = body.get("ineligibility_reason")

    # Segregation-of-duties (PRD §2.1): caseworker may not be the same as a prior
    # caseworker who issued an INELIGIBLE determination on this application. The
    # determination may currently be OVERTURNED (post-grant) — but at decision
    # time the outcome was INELIGIBLE, and the prior decider is still recorded.
    # We treat any determination whose original outcome was INELIGIBLE (i.e.
    # outcome in {INELIGIBLE, OVERTURNED}) as a prior denial for this rule.
    for d in STORE.determinations.values():
        if d["application_id"] != app["id"]:
            continue
        if d["outcome"] in ("INELIGIBLE", "OVERTURNED"):
            if d.get("_decider_user_id") == g.user_id:
                raise_error(
                    "ERR_FORBIDDEN_SAME_ACTOR",
                    "Caseworker who issued the prior INELIGIBLE determination cannot re-decide",
                )

    if decision == "APPROVE":
        # Eligibility check
        check_application_eligibility(app)
        # All preconditions OK — perform mutations atomically
        with lock():
            # First check enrollment-overlap for every non-EXCLUDED applicant before committing.
            applicants = [a for a in list_applicants_of_household(household_id)
                          if a["dependent_status"] != "EXCLUDED"]
            coverage_start_dt = CLOCK.now()
            coverage_end_dt = coverage_start_dt + days(365)
            for a in applicants:
                if _check_enrollment_overlaps(a["id"], coverage_start_dt, coverage_end_dt):
                    raise_error("ERR_ENROLLMENT_OVERLAP",
                                "New coverage window overlaps an existing non-TERMINATED enrollment")
            # Create the Determination
            did = gen_id()
            d_row = {
                "id": did,
                "application_id": app["id"],
                "decided_at": CLOCK.now_iso(),
                "outcome": "ELIGIBLE",
                "ineligibility_reason": None,
                "computed_magi": app.get("snapshot_magi"),
                "computed_fpl_percent": app.get("snapshot_fpl_percent"),
                "applied_rule_variant": app["rule_variant"],
                "_decider_user_id": g.user_id,
            }
            stamp_create(d_row)
            STORE.determinations[did] = d_row
            # Create Enrollments — one per non-EXCLUDED applicant
            for a in applicants:
                eid = gen_id()
                e_row = {
                    "id": eid,
                    "applicant_id": a["id"],
                    "determination_id": did,
                    "coverage_start": iso_format(coverage_start_dt),
                    "coverage_end": iso_format(coverage_end_dt),
                    "coverage_status": "ACTIVE",
                    "redetermination_due_at": iso_format(coverage_start_dt + days(365)),
                }
                stamp_create(e_row)
                STORE.enrollments[eid] = e_row
            # Application transitions to APPROVED
            app["status"] = "APPROVED"
            bump(app)
            # Recompute household.active_enrollment_count → bump household
            bump(household)
        return success_object(project_determination(d_row))
    else:
        # DENY: optional ineligibility_reason; validate if supplied
        if ineligibility_reason is not None:
            if ineligibility_reason not in _INELIGIBILITY_REASONS:
                raise_error("ERR_INVALID_REQUEST", "ineligibility_reason invalid")
        with lock():
            did = gen_id()
            d_row = {
                "id": did,
                "application_id": app["id"],
                "decided_at": CLOCK.now_iso(),
                "outcome": "INELIGIBLE",
                "ineligibility_reason": ineligibility_reason,
                "computed_magi": app.get("snapshot_magi"),
                "computed_fpl_percent": app.get("snapshot_fpl_percent"),
                "applied_rule_variant": app["rule_variant"],
                "_decider_user_id": g.user_id,
            }
            stamp_create(d_row)
            STORE.determinations[did] = d_row
            app["status"] = "DENIED"
            bump(app)
        return success_object(project_determination(d_row))


@bp.route("/households/<household_id>/applications/<application_id>/withdraw", methods=["POST"])
@require_roles("IntakeWorker")
def withdraw_application(household_id, application_id):
    _, app = _resolve_household_application(household_id, application_id)
    if app["status"] not in ("DRAFT", "UNDER_REVIEW"):
        raise_error("ERR_INVALID_STATE", "Application must be DRAFT or UNDER_REVIEW to withdraw")
    with lock():
        app["status"] = "WITHDRAWN"
        bump(app)
    return success_object(project_application(app))
