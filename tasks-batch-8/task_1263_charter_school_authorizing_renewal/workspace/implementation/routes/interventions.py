"""Intervention notices and corrective action plans (PRD §3.5)."""
from datetime import timedelta

from flask import Blueprint

import db
import errors
from clock import now_dt, now_iso, to_iso
from errors import raise_error
from middleware import (
    ALL_ROLES,
    body,
    check_operator_owns,
    require_field,
    require_non_empty_string,
    require_roles,
)
from response import success_object
from routes.common import get_or_404, paginate
from services import cascade

bp = Blueprint("interventions", __name__)

LEVELS = {"NOTICE", "PROBATION", "REVOCATION_REVIEW"}
DOMAINS = {"ACADEMIC", "FINANCIAL", "OPERATIONAL", "COMPLIANCE"}
NEXT_LEVEL = {"NOTICE": "PROBATION", "PROBATION": "REVOCATION_REVIEW"}


@bp.post("/authorizer/schools/<id>/interventions")
def create_intervention(id):
    require_roles(["AuthorizerStaff"])
    school = get_or_404("schools", id)
    if school["status"] != "OPEN":
        raise_error(errors.ERR_SCHOOL_NOT_OPEN, "Intervention creation requires an OPEN school")
    data = body()
    level = require_non_empty_string(data, "level")
    if level not in LEVELS:
        raise_error(errors.ERR_INVALID_REQUEST, "level must be NOTICE|PROBATION|REVOCATION_REVIEW")
    domain = require_non_empty_string(data, "domain")
    if domain not in DOMAINS:
        raise_error(errors.ERR_INVALID_REQUEST, "domain must be ACADEMIC|FINANCIAL|OPERATIONAL|COMPLIANCE")
    reason = require_non_empty_string(data, "reason")
    record = db.stamp_new({
        "school_id": id,
        "level": level,
        "domain": domain,
        "reason": reason,
        "issued_by_user_id": None,
        "resolved_by_user_id": None,
        "corrective_due_date": None,
        "successor_notice_id": None,
        "status": "DRAFT",
    })
    db.insert("interventions", record)
    return success_object(record, 201)


@bp.get("/authorizer/schools/<id>/interventions")
def list_school_interventions(id):
    require_roles(ALL_ROLES)
    get_or_404("schools", id)
    records = [n for n in db.all_records("interventions") if n["school_id"] == id]
    return paginate(records)


@bp.get("/authorizer/interventions/<id>")
def get_intervention(id):
    require_roles(ALL_ROLES)
    return success_object(get_or_404("interventions", id))


@bp.post("/authorizer/interventions/<id>/issue")
def issue_intervention(id):
    user_id, _role = require_roles(["AuthorizerStaff"])
    notice = get_or_404("interventions", id)
    if notice["status"] != "DRAFT":
        raise_error(errors.ERR_NOTICE_INVALID_STATE, "Notice is not DRAFT")
    notice["status"] = "ISSUED"
    notice["issued_by_user_id"] = user_id
    notice["corrective_due_date"] = to_iso(now_dt() + timedelta(days=30))
    db.touch(notice)
    return success_object(notice)


@bp.post("/authorizer/interventions/<id>/escalate")
def escalate_intervention(id):
    user_id, _role = require_roles(["BoardMember"])
    notice = get_or_404("interventions", id)
    if notice["status"] != "ISSUED" or notice["level"] == "REVOCATION_REVIEW":
        raise_error(errors.ERR_NOTICE_INVALID_STATE, "Notice is not ISSUED or has nowhere higher to go")
    notice["status"] = "ESCALATED"
    db.touch(notice)
    successor = db.stamp_new({
        "school_id": notice["school_id"],
        "level": NEXT_LEVEL[notice["level"]],
        "domain": notice["domain"],
        "reason": notice["reason"],
        "issued_by_user_id": user_id,
        "resolved_by_user_id": None,
        "corrective_due_date": to_iso(now_dt() + timedelta(days=30)),
        "successor_notice_id": None,
        "status": "ISSUED",
    })
    db.insert("interventions", successor)
    notice["successor_notice_id"] = successor["id"]
    db.touch(notice)
    return success_object(notice)


@bp.post("/authorizer/interventions/<id>/resolve")
def resolve_intervention(id):
    user_id, _role = require_roles(["AuthorizerStaff"])
    notice = get_or_404("interventions", id)
    if notice["status"] != "ISSUED":
        raise_error(errors.ERR_NOTICE_INVALID_STATE, "Notice is not ISSUED")
    if user_id == notice["issued_by_user_id"]:
        raise_error(errors.ERR_SOD_NOTICE_SELF_RESOLVE, "Resolver must differ from issuer")
    if notice["level"] in ("PROBATION", "REVOCATION_REVIEW"):
        has_accepted = any(
            p["intervention_id"] == id and p["status"] == "ACCEPTED"
            for p in db.all_records("corrective_plans")
        )
        if not has_accepted:
            raise_error(errors.ERR_NO_ACCEPTED_CORRECTIVE_PLAN, "No ACCEPTED corrective plan for this notice")
    notice["status"] = "RESOLVED"
    notice["resolved_by_user_id"] = user_id
    db.touch(notice)
    school = db.get("schools", notice["school_id"])
    if school is not None:
        cascade.upgrade_school_standing(school, notice["domain"])
    return success_object(notice)


@bp.post("/authorizer/interventions/<id>/corrective-plans")
def create_plan(id):
    user_id, role = require_roles(["SchoolOperator"])
    notice = get_or_404("interventions", id)
    check_operator_owns(user_id, role, notice["school_id"])
    data = body()
    plan_text = require_non_empty_string(data, "plan_text")
    expected = require_field(data, "expected_intervention_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_error(errors.ERR_INVALID_REQUEST, "expected_intervention_version must be an integer")
    # OCC layer 3.6 (§2.7)
    if expected != notice["version"]:
        raise_error(errors.ERR_STALE_INTERVENTION_VERSION, "expected_intervention_version does not match notice version")
    # State precondition (layer 4)
    if notice["status"] != "ISSUED":
        raise_error(errors.ERR_NOTICE_INVALID_STATE, "Notice is not ISSUED")
    # Temporal (layer 6): clock at or before corrective_due_date.
    from clock import parse as parse_iso
    due = parse_iso(notice["corrective_due_date"]) if notice["corrective_due_date"] else None
    if due is not None and now_dt() > due:
        raise_error(errors.ERR_CORRECTIVE_PLAN_OVERDUE, "Corrective plan submitted after the due date")
    # Aggregate (layer 7): no other SUBMITTED|ACCEPTED plan for the notice.
    for p in db.all_records("corrective_plans"):
        if p["intervention_id"] == id and p["status"] in ("SUBMITTED", "ACCEPTED"):
            raise_error(errors.ERR_PLAN_ALREADY_ACTIVE, "A SUBMITTED or ACCEPTED plan already exists")
    record = db.stamp_new({
        "intervention_id": id,
        "plan_text": plan_text,
        "submitted_at": now_iso(),
        "reviewed_by_user_id": None,
        "review_notes": None,
        "status": "SUBMITTED",
    })
    db.insert("corrective_plans", record)
    # Plan create is a version-advancing write on the notice (§2.7).
    db.touch(notice)
    return success_object(record, 201)


@bp.get("/authorizer/interventions/<id>/corrective-plans")
def list_plans(id):
    require_roles(ALL_ROLES)
    get_or_404("interventions", id)
    records = [p for p in db.all_records("corrective_plans") if p["intervention_id"] == id]
    return paginate(records)


@bp.post("/authorizer/corrective-plans/<id>/review")
def review_plan(id):
    user_id, _role = require_roles(["AuthorizerStaff"])
    plan = get_or_404("corrective_plans", id)
    if plan["status"] != "SUBMITTED":
        raise_error(errors.ERR_PLAN_INVALID_STATE, "Plan is not SUBMITTED")
    data = body()
    outcome = require_non_empty_string(data, "outcome")
    if outcome not in ("ACCEPTED", "RETURNED"):
        raise_error(errors.ERR_INVALID_REQUEST, "outcome must be ACCEPTED or RETURNED")
    notes = data.get("review_notes")
    if outcome == "RETURNED" and (not isinstance(notes, str) or notes == ""):
        raise_error(errors.ERR_INVALID_REQUEST, "review_notes required when RETURNED")
    plan["status"] = outcome
    plan["reviewed_by_user_id"] = user_id
    plan["review_notes"] = notes if isinstance(notes, str) else None
    db.touch(plan)
    return success_object(plan)


@bp.post("/authorizer/corrective-plans/<id>/resubmit")
def resubmit_plan(id):
    user_id, role = require_roles(["SchoolOperator"])
    plan = get_or_404("corrective_plans", id)
    notice = db.get("interventions", plan["intervention_id"])
    owning_school_id = notice["school_id"] if notice else None
    check_operator_owns(user_id, role, owning_school_id)
    if plan["status"] != "RETURNED":
        raise_error(errors.ERR_PLAN_INVALID_STATE, "Plan is not RETURNED")
    data = body()
    plan_text = require_non_empty_string(data, "plan_text")
    from clock import parse as parse_iso
    due = parse_iso(notice["corrective_due_date"]) if notice and notice["corrective_due_date"] else None
    if due is not None and now_dt() > due:
        raise_error(errors.ERR_CORRECTIVE_PLAN_OVERDUE, "Corrective plan resubmitted after the due date")
    plan["plan_text"] = plan_text
    plan["submitted_at"] = now_iso()
    plan["reviewed_by_user_id"] = None
    plan["review_notes"] = None
    plan["status"] = "SUBMITTED"
    db.touch(plan)
    return success_object(plan)
