"""Parent consent records: ad-hoc scope creation, list, detail, record-response."""
from flask import Blueprint, request

from db import db, create_record, now, touch
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import body, req_bool, req_enum, req_str, require_roles
from response import success
from routes import list_response
from services import (CONSENT_SCOPES, consent_out, get_consent, get_evaluation,
                      get_plan, get_student, posture_gate, school_of_student)

bp = Blueprint("consents", __name__)

CONSENT_READERS = ("District504Director", "Section504Coordinator", "SchoolPrincipal", "Parent")


@bp.post("/consent-records")
@require_roles("Section504Coordinator")
def create_consent():
    d = body()
    stu = get_student(req_str(d, "student_id"))
    posture_gate(school_of_student(stu))
    scope = req_enum(d, "consent_scope", CONSENT_SCOPES)
    plan_id = d.get("plan_id")
    evaluation_id = d.get("evaluation_id")
    if (plan_id is None) == (evaluation_id is None):
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1],
                       "Exactly one of plan_id or evaluation_id must be set")
    if plan_id is not None:
        plan = get_plan(plan_id)
        plan_id = plan["id"]
    if evaluation_id is not None:
        ev = get_evaluation(evaluation_id)
        evaluation_id = ev["id"]
    rec = create_record(db.consents, {
        "student_id": stu["id"],
        "evaluation_id": evaluation_id,
        "plan_id": plan_id,
        "consent_scope": scope,
        "consent_status": "REQUESTED",
        "requested_at": now(),
        "responded_at": None,
        "responded_by_parent_ref": None,
    })
    return success(consent_out(rec), 201)


@bp.get("/consent-records")
@require_roles(*CONSENT_READERS)
def list_consents():
    items = list(db.consents.values())
    student_id = request.args.get("student_id")
    evaluation_id = request.args.get("evaluation_id")
    plan_id = request.args.get("plan_id")
    scope = request.args.get("consent_scope")
    status = request.args.get("consent_status")
    if student_id is not None:
        items = [c for c in items if c["student_id"] == student_id]
    if evaluation_id is not None:
        items = [c for c in items if c.get("evaluation_id") == evaluation_id]
    if plan_id is not None:
        items = [c for c in items if c.get("plan_id") == plan_id]
    if scope is not None:
        items = [c for c in items if c["consent_scope"] == scope]
    if status is not None:
        items = [c for c in items if c["consent_status"] == status]
    return list_response(items, consent_out)


@bp.get("/consent-records/<consentId>")
@require_roles(*CONSENT_READERS)
def get_consent_detail(consentId):
    return success(consent_out(get_consent(consentId)), 200)


@bp.post("/consent-records/<consentId>/record-response")
@require_roles("Section504Coordinator")
def record_response(consentId):
    rec = get_consent(consentId)
    stu = get_student(rec["student_id"])
    posture_gate(school_of_student(stu))
    d = body()
    granted = req_bool(d, "granted")
    parent_ref = req_str(d, "responded_by_parent_ref")
    rec["consent_status"] = "GRANTED" if granted else "DENIED"
    rec["responded_at"] = now()
    rec["responded_by_parent_ref"] = parent_ref
    touch(rec)
    return success(consent_out(rec), 200)
