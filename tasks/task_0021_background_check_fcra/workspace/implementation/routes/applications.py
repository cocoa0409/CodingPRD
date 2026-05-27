"""Application endpoints and lifecycle transitions."""

from flask import Blueprint, request

from db import db
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from util import (
    stamp_common_create, stamp_update, get_application, get_applicant,
    get_jurisdiction, get_json_body, require_fields, check_occ,
    parse_pagination, page, sort_by_created_at,
)
from services.audit import append_audit


bp = Blueprint("applications", __name__)


def _serialize(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "applicant_id": a["applicant_id"],
        "jurisdiction_id": a["jurisdiction_id"],
        "position_title": a["position_title"],
        "salary_history_disclosed": a["salary_history_disclosed"],
        "status": a["status"],
        "conditional_offer_at": a["conditional_offer_at"],
    }


@bp.route("/api/v1/applications", methods=["POST"])
@require_roles("Applicant", "Recruiter")
def create_application(_user_id, _role):
    body = get_json_body()
    require_fields(body, "applicant_id", "jurisdiction_id", "position_title")
    applicant_id = body["applicant_id"]
    jurisdiction_id = body["jurisdiction_id"]
    position_title = body["position_title"]
    salary_history_disclosed = body.get("salary_history_disclosed", None)

    # Existence (FK) check
    get_applicant(applicant_id)
    get_jurisdiction(jurisdiction_id)

    if not isinstance(position_title, str) or not position_title.strip():
        raise_api("ERR_INVALID_REQUEST", "position_title must be non-empty string")
    if salary_history_disclosed is not None and not isinstance(salary_history_disclosed, (int, float)):
        raise_api("ERR_INVALID_REQUEST", "salary_history_disclosed must be a number or null")
    if isinstance(salary_history_disclosed, bool):  # bool is subclass of int in Python
        raise_api("ERR_INVALID_REQUEST", "salary_history_disclosed must be numeric, not boolean")

    a = {
        "applicant_id": applicant_id,
        "jurisdiction_id": jurisdiction_id,
        "position_title": position_title,
        "salary_history_disclosed": salary_history_disclosed,
        "status": "DRAFT",
        "conditional_offer_at": None,
    }
    stamp_common_create(a)
    db.applications[a["id"]] = a
    return success(_serialize(a), 201)


@bp.route("/api/v1/applications/<aid>", methods=["GET"])
@require_roles("Applicant", "Recruiter", "ComplianceOfficer")
def get_application_route(aid, _user_id, _role):
    a = get_application(aid)
    return success(_serialize(a))


@bp.route("/api/v1/applications", methods=["GET"])
@require_roles("Recruiter", "ComplianceOfficer")
def list_applications(_user_id, _role):
    limit, offset = parse_pagination()
    applicant_id = request.args.get("applicant_id")
    jurisdiction_id = request.args.get("jurisdiction_id")
    status = request.args.get("status")
    items = list(db.applications.values())
    if applicant_id is not None:
        items = [a for a in items if a["applicant_id"] == applicant_id]
    if jurisdiction_id is not None:
        items = [a for a in items if a["jurisdiction_id"] == jurisdiction_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sort_by_created_at(items)
    page_items, total = page(items, limit, offset)
    return list_success([_serialize(a) for a in page_items], limit, offset, total)


# ----- Transitions -----

def _ensure_state(application, allowed):
    if application["status"] not in allowed:
        raise_api(
            "ERR_INVALID_STATE",
            f"Application.status={application['status']} not in {allowed}",
        )


@bp.route("/api/v1/applications/<aid>/submit", methods=["POST"])
@require_roles("Applicant")
def submit_application(aid, _user_id, _role):
    a = get_application(aid)
    body = get_json_body()
    _ensure_state(a, {"DRAFT"})
    check_occ(body, "expected_application_version", a["version"])
    # Business rule: at least one GRANTED consent exists for this application
    has_granted = any(
        c["application_id"] == aid and c["consent_status"] == "GRANTED"
        for c in db.consents.values()
    )
    if not has_granted:
        raise_api("ERR_INVALID_STATE", "Application requires a GRANTED consent before submission")
    # Salary history ban
    jurisdiction = db.jurisdictions[a["jurisdiction_id"]]
    if jurisdiction.get("salary_history_ban_enabled") and a.get("salary_history_disclosed") is not None:
        raise_api(
            "ERR_SALARY_HISTORY_DISCLOSED_BANNED",
            "salary_history_disclosed must be null in salary-history-ban jurisdictions",
        )
    prior = a["status"]
    a["status"] = "SUBMITTED"
    stamp_update(a)
    append_audit(_role, _user_id, "APPLICATION_SUBMIT", "Application", a["id"], prior, a["status"])
    return success(_serialize(a))


@bp.route("/api/v1/applications/<aid>/conditional-offer", methods=["POST"])
@require_roles("Recruiter")
def conditional_offer(aid, _user_id, _role):
    a = get_application(aid)
    body = get_json_body()
    _ensure_state(a, {"SUBMITTED"})
    check_occ(body, "expected_application_version", a["version"])
    prior = a["status"]
    a["status"] = "CONDITIONAL_OFFER"
    a["conditional_offer_at"] = db.current_utc_iso()
    stamp_update(a)
    # Capture the recruiter user_id for segregation-of-duties checks
    db.conditional_offer_actor[a["id"]] = _user_id
    append_audit(_role, _user_id, "CONDITIONAL_OFFER", "Application", a["id"], prior, a["status"])
    return success(_serialize(a))


@bp.route("/api/v1/applications/<aid>/hire", methods=["POST"])
@require_roles("Recruiter")
def hire_application(aid, _user_id, _role):
    a = get_application(aid)
    body = get_json_body()
    _ensure_state(a, {"CONDITIONAL_OFFER"})
    check_occ(body, "expected_application_version", a["version"])
    # Require an order in COMPLETE+CLEAR
    matching = [
        o for o in db.orders.values()
        if o["application_id"] == a["id"]
        and o["status"] == "COMPLETE"
        and o.get("overall_result") == "CLEAR"
    ]
    if not matching:
        raise_api("ERR_INVALID_STATE", "Cannot hire: no COMPLETE+CLEAR background-check order")
    prior = a["status"]
    a["status"] = "HIRED"
    stamp_update(a)
    append_audit(_role, _user_id, "HIRE", "Application", a["id"], prior, a["status"])
    return success(_serialize(a))


@bp.route("/api/v1/applications/<aid>/withdraw", methods=["POST"])
@require_roles("Applicant")
def withdraw_application(aid, _user_id, _role):
    a = get_application(aid)
    body = get_json_body()
    _ensure_state(a, {"DRAFT", "SUBMITTED"})
    check_occ(body, "expected_application_version", a["version"])
    prior = a["status"]
    a["status"] = "WITHDRAWN"
    stamp_update(a)
    append_audit(_role, _user_id, "APPLICATION_WITHDRAW", "Application", a["id"], prior, a["status"])
    return success(_serialize(a))
