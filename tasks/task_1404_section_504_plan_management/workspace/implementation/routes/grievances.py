"""Grievances: file, informal, formal, resolve (OCC), OCR escalation, close.

All grievance mutations are exempt from the blanket AUDIT_HOLD posture gate —
the grievance lifecycle is the remediation path that lets a school dig out of
AUDIT_HOLD (resolve/close reduce the open-grievance score; escalate-to-ocr is a
district act that must remain available while a hold is in effect).
"""
from datetime import timedelta

from flask import Blueprint, g, request

from db import db, create_record, now, touch
from errors import (ERR_GRIEVANCE_NOT_FILED, ERR_GRIEVANCE_NOT_FORMAL,
                    ERR_GRIEVANCE_NOT_INFORMAL, ERR_GRIEVANCE_NOT_ESCALATED,
                    ERR_SEGREGATION_OF_DUTIES, ERR_STALE_GRIEVANCE_VERSION,
                    raise_err)
from middleware import body, opt_str, req_enum, req_int, req_str, require_roles
from response import success
from routes import list_response
from services import (FORMAL_RESOLUTION_WINDOW_DAYS, GRIEVANCE_CATEGORIES,
                      INFORMAL_RESOLUTION_WINDOW_DAYS, emit, get_grievance,
                      get_plan, get_student, grievance_out,
                      recompute_posture_for_student, school_of_student)

bp = Blueprint("grievances", __name__)

GRIEVANCE_READERS = ("District504Director", "Section504Coordinator", "SchoolPrincipal", "Parent")


@bp.post("/grievances")
@require_roles("Parent", "Section504Coordinator")
def create_grievance():
    d = body()
    stu = get_student(req_str(d, "student_id"))
    school = school_of_student(stu)
    plan_id = opt_str(d, "plan_id", None)
    if plan_id is not None:
        plan_id = get_plan(plan_id)["id"]
    rec = create_record(db.grievances, {
        "student_id": stu["id"],
        "plan_id": plan_id,
        "filed_by_parent_ref": req_str(d, "filed_by_parent_ref"),
        "grievance_category": req_enum(d, "grievance_category", GRIEVANCE_CATEGORIES),
        "description": req_str(d, "description"),
        "grievance_status": "FILED",
        "filed_at": now(),
        "resolution_deadline": None,
        "resolved_by_staff_id": None,
        "intake_staff_id": None,
    })
    emit("GRIEVANCE_FILED", school["id"], rec["id"],
         g.user_id if g.user_role != "Parent" else None,
         {"student_id": stu["id"], "grievance_category": rec["grievance_category"]})
    recompute_posture_for_student(stu)
    return success(grievance_out(rec), 201)


@bp.get("/grievances")
@require_roles(*GRIEVANCE_READERS)
def list_grievances():
    items = list(db.grievances.values())
    student_id = request.args.get("student_id")
    plan_id = request.args.get("plan_id")
    status = request.args.get("grievance_status")
    if student_id is not None:
        items = [gr for gr in items if gr["student_id"] == student_id]
    if plan_id is not None:
        items = [gr for gr in items if gr.get("plan_id") == plan_id]
    if status is not None:
        items = [gr for gr in items if gr["grievance_status"] == status]
    return list_response(items, grievance_out)


@bp.get("/grievances/<grievanceId>")
@require_roles(*GRIEVANCE_READERS)
def get_grievance_detail(grievanceId):
    return success(grievance_out(get_grievance(grievanceId)), 200)


@bp.post("/grievances/<grievanceId>/begin-informal")
@require_roles("Section504Coordinator")
def begin_informal(grievanceId):
    gr = get_grievance(grievanceId)
    if gr["grievance_status"] != "FILED":
        raise_err(ERR_GRIEVANCE_NOT_FILED, "Grievance must be FILED to begin informal resolution")
    gr["intake_staff_id"] = g.user_id
    gr["resolution_deadline"] = gr["filed_at"] + timedelta(days=INFORMAL_RESOLUTION_WINDOW_DAYS)
    gr["grievance_status"] = "INFORMAL_RESOLUTION"
    touch(gr)
    return success(grievance_out(gr), 200)


@bp.post("/grievances/<grievanceId>/escalate-to-formal")
@require_roles("Section504Coordinator")
def escalate_to_formal(grievanceId):
    gr = get_grievance(grievanceId)
    if gr["grievance_status"] != "INFORMAL_RESOLUTION":
        raise_err(ERR_GRIEVANCE_NOT_INFORMAL,
                  "Grievance must be INFORMAL_RESOLUTION to escalate to formal")
    gr["grievance_status"] = "FORMAL_INVESTIGATION"
    gr["resolution_deadline"] = now() + timedelta(days=FORMAL_RESOLUTION_WINDOW_DAYS)
    touch(gr)
    return success(grievance_out(gr), 200)


@bp.post("/grievances/<grievanceId>/resolve")
@require_roles("District504Director")
def resolve_grievance(grievanceId):
    gr = get_grievance(grievanceId)
    stu = get_student(gr["student_id"])
    school = school_of_student(stu)
    d = body()
    expected = req_int(d, "expected_grievance_version")
    if expected != gr["version"]:
        emit("OCC_CONFLICT", school["id"], gr["id"], g.user_id,
             {"occ_field": "expected_grievance_version", "expected": expected,
              "actual": gr["version"], "endpoint": "POST /grievances/{grievanceId}/resolve"})
        raise_err(ERR_STALE_GRIEVANCE_VERSION,
                  "expected_grievance_version does not match the grievance's current version")
    if gr["grievance_status"] not in ("INFORMAL_RESOLUTION", "FORMAL_INVESTIGATION"):
        raise_err(ERR_GRIEVANCE_NOT_INFORMAL,
                  "Grievance must be INFORMAL_RESOLUTION or FORMAL_INVESTIGATION to resolve")
    if gr.get("intake_staff_id") is not None and gr["intake_staff_id"] == g.user_id:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "The resolver must differ from the intake officer")
    gr["resolved_by_staff_id"] = g.user_id
    gr["grievance_status"] = "RESOLVED"
    touch(gr)
    recompute_posture_for_student(stu)
    return success(grievance_out(gr), 200)


@bp.post("/grievances/<grievanceId>/escalate-to-ocr")
@require_roles("District504Director")
def escalate_to_ocr(grievanceId):
    gr = get_grievance(grievanceId)
    stu = get_student(gr["student_id"])
    school = school_of_student(stu)
    if gr["grievance_status"] != "FORMAL_INVESTIGATION":
        raise_err(ERR_GRIEVANCE_NOT_FORMAL,
                  "Grievance must be FORMAL_INVESTIGATION to escalate to OCR")
    gr["grievance_status"] = "ESCALATED_TO_OCR"
    touch(gr)
    emit("GRIEVANCE_ESCALATED", school["id"], gr["id"], g.user_id,
         {"student_id": stu["id"]})
    recompute_posture_for_student(stu)
    return success(grievance_out(gr), 200)


@bp.post("/grievances/<grievanceId>/close")
@require_roles("District504Director")
def close_grievance(grievanceId):
    gr = get_grievance(grievanceId)
    stu = get_student(gr["student_id"])
    if gr["grievance_status"] != "ESCALATED_TO_OCR":
        raise_err(ERR_GRIEVANCE_NOT_ESCALATED,
                  "Grievance must be ESCALATED_TO_OCR to close")
    gr["grievance_status"] = "CLOSED"
    touch(gr)
    recompute_posture_for_student(stu)
    return success(grievance_out(gr), 200)
