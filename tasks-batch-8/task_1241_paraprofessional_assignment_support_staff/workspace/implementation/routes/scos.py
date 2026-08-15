"""ServiceChangeOrder endpoints (PRD §3.2): file, approve, return, effectuate, cancel."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_CHANGE_ORDER_INVALID_STATE, ERR_OPEN_CHANGE_ORDER_EXISTS,
    ERR_STUDENT_NOT_ASSIGNABLE, ApiError,
)
from middleware import auth_context, require_role
from response import paginate, success
from util import (
    CHANGE_TYPES, QUALIFICATIONS, as_enum, as_int, as_str, bad_request,
    body_json, need,
)

bp = Blueprint("scos", __name__)

COORD = {"SpecialEdCoordinator"}
ADMIN = {"DistrictStaffingAdmin"}
ANY = {"Any"}


def _auth(allowed):
    auth_context()
    require_role(request.headers.get("X-User-Role"), allowed)


@bp.post("/sped-staffing/service-change-orders")
def create_sco():
    _auth(COORD)
    body = body_json(request)
    student_id = need(body, "student_id")
    student = svc.get_student(as_str(student_id, "student_id"))
    # Body FK existence (BUILDING_TRANSFER target), priority 3.
    new_building_id = body.get("new_building_id")
    new_building = None
    if new_building_id is not None:
        new_building = svc.get_building(as_str(new_building_id, "new_building_id"))
    # Structural validation per change_type.
    change_type = as_enum(need(body, "change_type"), "change_type", CHANGE_TYPES)
    reason = as_str(need(body, "reason"), "reason")
    new_minutes = None
    new_qual = None
    if change_type == "MINUTES_CHANGE":
        new_minutes = as_int(need(body, "new_minutes_per_week"),
                             "new_minutes_per_week")
        if new_minutes <= 0:
            bad_request("new_minutes_per_week must be > 0")
    elif change_type == "QUALIFICATION_CHANGE":
        new_qual = as_enum(need(body, "new_required_qualification"),
                           "new_required_qualification", QUALIFICATIONS)
    elif change_type == "BUILDING_TRANSFER":
        if new_building is None:
            bad_request("new_building_id is required for BUILDING_TRANSFER")
    # State: student must be ACTIVE_IEP.
    if student["status"] != "ACTIVE_IEP":
        raise ApiError(ERR_STUDENT_NOT_ASSIGNABLE, 409,
                       "filing a change order requires student ACTIVE_IEP")
    # Uniqueness: no other FILED/APPROVED order for the student.
    for o in db.STORE["scos"].values():
        if (o["student_id"] == student["id"]
                and o["status"] in ("FILED", "APPROVED")):
            raise ApiError(ERR_OPEN_CHANGE_ORDER_EXISTS, 409,
                           "student already has an open service change order")
    order = {
        "plan_id": student["plan_id"],
        "student_id": student["id"],
        "change_type": change_type,
        "new_minutes_per_week": new_minutes,
        "new_required_qualification": new_qual,
        "new_building_id": new_building["id"] if new_building else None,
        "reason": reason,
        "status": "FILED",
    }
    svc.stamp_new(order)
    db.STORE["scos"][order["id"]] = order
    student["status"] = "SERVICE_CHANGE_PENDING"
    svc.touch(student)
    return success(svc.ser_sco(order), "object", 201)


@bp.get("/sped-staffing/service-change-orders")
def list_scos():
    _auth(ANY)
    plan_id = request.args.get("plan_id")
    student_id = request.args.get("student_id")
    new_building_id = request.args.get("new_building_id")
    status = request.args.get("status")
    items = []
    for o in svc.sorted_records("scos"):
        if plan_id is not None and o["plan_id"] != plan_id:
            continue
        if student_id is not None and o["student_id"] != student_id:
            continue
        if new_building_id is not None and o["new_building_id"] != new_building_id:
            continue
        if status is not None and o["status"] != status:
            continue
        items.append(svc.ser_sco(o))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/sped-staffing/service-change-orders/<orderId>")
def get_sco(orderId):
    _auth(ANY)
    order = svc.get_sco(orderId)
    return success(svc.ser_sco(order), "object", 200)


@bp.post("/sped-staffing/service-change-orders/<orderId>/approve")
def approve_sco(orderId):
    _auth(ADMIN)
    order = svc.get_sco(orderId)
    if order["status"] != "FILED":
        raise ApiError(ERR_CHANGE_ORDER_INVALID_STATE, 409,
                       "approve requires change order FILED")
    order["status"] = "APPROVED"
    svc.touch(order)
    return success(svc.ser_sco(order), "object", 200)


@bp.post("/sped-staffing/service-change-orders/<orderId>/return")
def return_sco(orderId):
    _auth(ADMIN)
    order = svc.get_sco(orderId)
    if order["status"] != "APPROVED":
        raise ApiError(ERR_CHANGE_ORDER_INVALID_STATE, 409,
                       "return requires change order APPROVED")
    order["status"] = "FILED"
    svc.touch(order)
    return success(svc.ser_sco(order), "object", 200)


@bp.post("/sped-staffing/service-change-orders/<orderId>/effectuate")
def effectuate_sco(orderId):
    _auth(COORD)
    order = svc.get_sco(orderId)
    if order["status"] != "APPROVED":
        raise ApiError(ERR_CHANGE_ORDER_INVALID_STATE, 409,
                       "effectuate requires change order APPROVED")
    student = db.STORE["students"][order["student_id"]]
    if student["status"] != "SERVICE_CHANGE_PENDING":
        raise ApiError(ERR_CHANGE_ORDER_INVALID_STATE, 409,
                       "student must still be SERVICE_CHANGE_PENDING")
    plan = db.STORE["plans"][order["plan_id"]]

    # Apply the order's new field values to the student record.
    if order["change_type"] == "MINUTES_CHANGE":
        student["iep_minutes_per_week"] = order["new_minutes_per_week"]
    elif order["change_type"] == "QUALIFICATION_CHANGE":
        student["required_qualification"] = order["new_required_qualification"]
    elif order["change_type"] == "BUILDING_TRANSFER":
        student["building_id"] = order["new_building_id"]
    student["status"] = ("EXITED" if order["change_type"] == "EXIT"
                         else "ACTIVE_IEP")
    svc.touch(student)

    # Three-hop reassignment cascade: end the student's live assignments with
    # SERVICE_CHANGED; each end releases minutes/committed and drives the
    # benefit-flip re-costing of the para's remaining proposals.
    live = [a for a in db.STORE["assignments"].values()
            if a["student_id"] == student["id"]
            and a["status"] in ("PROPOSED", "QUALIFICATION_VERIFIED",
                                "ACTIVE", "SUSPENDED")]
    svc.end_assignments_cascade(live, plan, "SERVICE_CHANGED")

    order["status"] = "EFFECTIVE"
    svc.touch(order)
    return success(svc.ser_sco(order), "object", 200)


@bp.post("/sped-staffing/service-change-orders/<orderId>/cancel")
def cancel_sco(orderId):
    _auth(COORD)
    order = svc.get_sco(orderId)
    if order["status"] not in ("FILED", "APPROVED"):
        raise ApiError(ERR_CHANGE_ORDER_INVALID_STATE, 409,
                       "cancel requires change order FILED or APPROVED")
    student = db.STORE["students"][order["student_id"]]
    if student["status"] == "SERVICE_CHANGE_PENDING":
        student["status"] = "ACTIVE_IEP"
        svc.touch(student)
    order["status"] = "CANCELLED"
    svc.touch(order)
    return success(svc.ser_sco(order), "object", 200)
