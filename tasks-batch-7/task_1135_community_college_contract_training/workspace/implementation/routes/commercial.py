"""Clock, Employer, and NeedsAssessment endpoints."""

from flask import Blueprint

import db
from db import now, stamp_new, store, touch
from middleware import auth_context, check_employer_scope, require_roles
from response import ok, ok_list, serialize
from services import lifecycle, lookups
from util import body_json, fmt_dt, pagination_args, req_list, req_str, require_dt

bp = Blueprint("commercial", __name__)

READ_ROLES = (
    "CollegeAdmin",
    "WorkforceCoordinator",
    "CredentialOfficer",
    "GrantOfficer",
    "EmployerContact",
    "BillingClerk",
    "Instructor",
)


def _paginate(items):
    items = sorted(items, key=lambda r: r["created_at"])
    limit, offset = pagination_args()
    page = items[offset : offset + limit]
    return ok_list([serialize(r) for r in page], len(items), limit, offset)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.route("/ct/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("CollegeAdmin")
    body = body_json()
    target = require_dt(body.get("to_iso8601"), "to_iso8601")
    db.set_now(target)
    lifecycle.run_clock_sweeps()
    return ok({"now": fmt_dt(now())})


# ---------------------------------------------------------------------------
# Employers
# ---------------------------------------------------------------------------

@bp.route("/ct/employers", methods=["POST"])
def create_employer():
    require_roles("CollegeAdmin", "WorkforceCoordinator")
    body = body_json()
    rec = stamp_new(
        {
            "id": db.new_id(),
            "legal_name": req_str(body, "legal_name"),
            "industry_code": req_str(body, "industry_code"),
            "contact_email": req_str(body, "contact_email"),
            "status": "PROSPECT",
            "lifetime_billed_cents": 0,
            "follow_on_pipeline_cents": 0,
        }
    )
    store["employers"][rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/ct/employers/<eid>", methods=["GET"])
def get_employer(eid):
    uid, role = require_roles(*READ_ROLES)
    employer = lookups.get_or_404("employers", eid, "Employer")
    check_employer_scope(uid, role, eid)
    return ok(serialize(employer))


@bp.route("/ct/employers/<eid>/needs-assessments", methods=["GET"])
def list_employer_assessments(eid):
    uid, role = require_roles(*READ_ROLES)
    lookups.get_or_404("employers", eid, "Employer")
    check_employer_scope(uid, role, eid)
    return _paginate(lookups.assessments_of_employer(eid))


@bp.route("/ct/employers/<eid>/training-agreements", methods=["GET"])
def list_employer_agreements(eid):
    uid, role = require_roles(*READ_ROLES)
    lookups.get_or_404("employers", eid, "Employer")
    check_employer_scope(uid, role, eid)
    return _paginate(lookups.agreements_of_employer(eid))


# ---------------------------------------------------------------------------
# NeedsAssessments
# ---------------------------------------------------------------------------

def _validate_modules(modules):
    for module in modules:
        if not isinstance(module, dict):
            from errors import fail

            fail("ERR_INVALID_REQUEST", "Each curriculum module must be an object")
        if not isinstance(module.get("code"), str) or not module.get("code"):
            from errors import fail

            fail("ERR_INVALID_REQUEST", "Each curriculum module requires a 'code' string")
        hours = module.get("hours")
        if isinstance(hours, bool) or not isinstance(hours, (int, float)):
            from errors import fail

            fail("ERR_INVALID_REQUEST", "Each curriculum module requires numeric 'hours'")
        if not isinstance(module.get("required_credential_codes"), list):
            from errors import fail

            fail(
                "ERR_INVALID_REQUEST",
                "Each curriculum module requires a 'required_credential_codes' list",
            )


@bp.route("/ct/employers/<eid>/needs-assessments", methods=["POST"])
def create_assessment(eid):
    require_roles("WorkforceCoordinator")
    lookups.get_or_404("employers", eid, "Employer")
    body = body_json()
    title = req_str(body, "title")
    skill_gaps = req_list(body, "skill_gaps")
    target_roles = req_list(body, "target_roles")
    modules = req_list(body, "curriculum_modules")
    _validate_modules(modules)
    rec = stamp_new(
        {
            "id": db.new_id(),
            "employer_id": eid,
            "title": title,
            "skill_gaps": skill_gaps,
            "target_roles": target_roles,
            "curriculum_modules": modules,
            "status": "DRAFT",
            "revision_round": 0,
            "approved_at": None,
        }
    )
    store["assessments"][rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/ct/needs-assessments/<aid>", methods=["GET"])
def get_assessment(aid):
    uid, role = require_roles(*READ_ROLES)
    assessment = lookups.get_or_404("assessments", aid, "NeedsAssessment")
    check_employer_scope(uid, role, assessment["employer_id"])
    return ok(serialize(assessment))


@bp.route("/ct/needs-assessments/<aid>/submit", methods=["POST"])
def submit_assessment(aid):
    require_roles("WorkforceCoordinator")
    assessment = lookups.get_or_404("assessments", aid, "NeedsAssessment")
    if not assessment.get("curriculum_modules"):
        from errors import fail

        fail("ERR_INVALID_REQUEST", "curriculum_modules must be non-empty to submit")
    if assessment["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        from errors import fail

        fail("ERR_INVALID_STATE", f"Cannot submit an assessment in {assessment['status']}")
    assessment["status"] = "SUBMITTED"
    touch(assessment)
    return ok(serialize(assessment))


@bp.route("/ct/needs-assessments/<aid>/approve", methods=["POST"])
def approve_assessment(aid):
    require_roles("CollegeAdmin")
    assessment = lookups.get_or_404("assessments", aid, "NeedsAssessment")
    if assessment["status"] != "SUBMITTED":
        from errors import fail

        fail("ERR_INVALID_STATE", f"Cannot approve an assessment in {assessment['status']}")
    assessment["status"] = "APPROVED"
    assessment["approved_at"] = fmt_dt(now())
    touch(assessment)
    return ok(serialize(assessment))


@bp.route("/ct/needs-assessments/<aid>/request_revision", methods=["POST"])
def request_revision(aid):
    require_roles("CollegeAdmin")
    assessment = lookups.get_or_404("assessments", aid, "NeedsAssessment")
    if assessment["status"] != "SUBMITTED":
        from errors import fail

        fail("ERR_INVALID_STATE", f"Cannot request revision of an assessment in {assessment['status']}")
    assessment["status"] = "REVISION_REQUESTED"
    assessment["revision_round"] += 1
    touch(assessment)
    return ok(serialize(assessment))
