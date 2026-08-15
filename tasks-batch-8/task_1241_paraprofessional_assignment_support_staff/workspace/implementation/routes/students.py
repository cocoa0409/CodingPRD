"""Student endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
import services as svc
from errors import ERR_PLAN_NOT_ACTIVE, ERR_STUDENT_NOT_ASSIGNABLE, ApiError
from middleware import auth_context, require_role
from response import paginate, success
from util import (
    QUALIFICATIONS, SERVICE_LEVELS, as_enum, as_int, as_str, bad_request,
    body_json, need, opt,
)

bp = Blueprint("students", __name__)

COORD = {"SpecialEdCoordinator"}
ANY = {"Any"}


def _auth(allowed):
    auth_context()
    require_role(request.headers.get("X-User-Role"), allowed)


@bp.post("/sped-staffing/students")
def create_student():
    _auth(COORD)
    body = body_json(request)
    plan_id = need(body, "plan_id")
    plan = svc.get_plan(as_str(plan_id, "plan_id"))
    building_id = need(body, "building_id")
    building = svc.get_building(as_str(building_id, "building_id"))
    student_ref = as_str(need(body, "student_ref"), "student_ref")
    service_level = as_enum(need(body, "iep_service_level"),
                            "iep_service_level", SERVICE_LEVELS)
    minutes = as_int(need(body, "iep_minutes_per_week"), "iep_minutes_per_week")
    if minutes <= 0:
        bad_request("iep_minutes_per_week must be > 0")
    req_qual = as_enum(opt(body, "required_qualification", "NONE"),
                       "required_qualification", QUALIFICATIONS)
    if plan["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(ERR_PLAN_NOT_ACTIVE, 409,
                       "student registration requires plan DRAFT or ACTIVE")
    for s in db.STORE["students"].values():
        if s["plan_id"] == plan["id"] and s["student_ref"] == student_ref:
            bad_request("student_ref must be unique within the plan")
    student = {
        "plan_id": plan["id"],
        "building_id": building["id"],
        "student_ref": student_ref,
        "iep_service_level": service_level,
        "iep_minutes_per_week": minutes,
        "required_qualification": req_qual,
        "status": "REGISTERED",
    }
    svc.stamp_new(student)
    db.STORE["students"][student["id"]] = student
    return success(svc.ser_student(student), "object", 201)


@bp.get("/sped-staffing/students")
def list_students():
    _auth(ANY)
    plan_id = request.args.get("plan_id")
    building_id = request.args.get("building_id")
    status = request.args.get("status")
    items = []
    for s in svc.sorted_records("students"):
        if plan_id is not None and s["plan_id"] != plan_id:
            continue
        if building_id is not None and s["building_id"] != building_id:
            continue
        if status is not None and s["status"] != status:
            continue
        items.append(svc.ser_student(s))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/sped-staffing/students/<studentId>")
def get_student(studentId):
    _auth(ANY)
    student = svc.get_student(studentId)
    return success(svc.ser_student(student), "object", 200)


@bp.post("/sped-staffing/students/<studentId>/activate-iep")
def activate_iep(studentId):
    _auth(COORD)
    student = svc.get_student(studentId)
    if student["status"] != "REGISTERED":
        raise ApiError(ERR_STUDENT_NOT_ASSIGNABLE, 409,
                       "activate-iep requires student REGISTERED")
    student["status"] = "ACTIVE_IEP"
    svc.touch(student)
    return success(svc.ser_student(student), "object", 200)
