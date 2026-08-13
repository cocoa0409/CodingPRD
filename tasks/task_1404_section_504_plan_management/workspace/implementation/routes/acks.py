"""Teacher acknowledgments: replacement rows, acknowledge, decline, auto-activation."""
from flask import Blueprint, g, request

from db import db, create_record, now, touch
from errors import (ERR_ACK_NOT_PENDING, ERR_ACK_OWNERSHIP_MISMATCH,
                    ERR_STAFF_TRAINING_NOT_CURRENT, raise_err)
from middleware import body, req_str, require_roles
from response import success
from routes import list_response
from services import (ack_gate_satisfied, ack_out, current_training_status,
                      get_ack, get_plan, get_staff, posture_gate,
                      school_of_plan)
from routes.plans import activate_plan

bp = Blueprint("acks", __name__)

ACK_READERS = ("District504Director", "Section504Coordinator", "SchoolPrincipal", "Teacher")


@bp.post("/teacher-acks")
@require_roles("Section504Coordinator")
def create_ack():
    d = body()
    plan = get_plan(req_str(d, "plan_id"))
    posture_gate(school_of_plan(plan))
    staff = get_staff(req_str(d, "staff_id"))
    rec = create_record(db.acks, {
        "plan_id": plan["id"],
        "staff_id": staff["id"],
        "ack_status": "PENDING",
        "ack_requested_at": now(),
        "ack_responded_at": None,
    })
    plan["all_teachers_acknowledged"] = ack_gate_satisfied(plan["id"])
    return success(ack_out(rec), 201)


@bp.get("/teacher-acks")
@require_roles(*ACK_READERS)
def list_acks():
    items = list(db.acks.values())
    plan_id = request.args.get("plan_id")
    staff_id = request.args.get("staff_id")
    status = request.args.get("ack_status")
    if plan_id is not None:
        items = [a for a in items if a["plan_id"] == plan_id]
    if staff_id is not None:
        items = [a for a in items if a["staff_id"] == staff_id]
    if status is not None:
        items = [a for a in items if a["ack_status"] == status]
    return list_response(items, ack_out)


@bp.get("/teacher-acks/<ackId>")
@require_roles(*ACK_READERS)
def get_ack_detail(ackId):
    return success(ack_out(get_ack(ackId)), 200)


@bp.post("/teacher-acks/<ackId>/acknowledge")
@require_roles("Teacher")
def acknowledge(ackId):
    ack = get_ack(ackId)
    plan = get_plan(ack["plan_id"])
    posture_gate(school_of_plan(plan))
    if ack["ack_status"] != "PENDING":
        raise_err(ERR_ACK_NOT_PENDING, "Acknowledgment must be PENDING")
    if ack["staff_id"] != g.user_id:
        raise_err(ERR_ACK_OWNERSHIP_MISMATCH,
                  "Only the teacher named on the acknowledgment row may respond to it")
    staff = db.staff.get(ack["staff_id"])
    if staff is None or current_training_status(staff) != "TRAINED_CURRENT":
        raise_err(ERR_STAFF_TRAINING_NOT_CURRENT,
                  "Acknowledging teacher must have current 504 training")
    ack["ack_status"] = "ACKNOWLEDGED"
    ack["ack_responded_at"] = now()
    touch(ack)
    plan["all_teachers_acknowledged"] = ack_gate_satisfied(plan["id"])
    if plan["all_teachers_acknowledged"] and plan["plan_status"] == "PENDING_TEACHER_ACK":
        activate_plan(plan, g.user_id)
    touch(plan)
    return success(ack_out(ack), 200)


@bp.post("/teacher-acks/<ackId>/decline")
@require_roles("Teacher")
def decline(ackId):
    ack = get_ack(ackId)
    plan = get_plan(ack["plan_id"])
    posture_gate(school_of_plan(plan))
    if ack["ack_status"] != "PENDING":
        raise_err(ERR_ACK_NOT_PENDING, "Acknowledgment must be PENDING")
    if ack["staff_id"] != g.user_id:
        raise_err(ERR_ACK_OWNERSHIP_MISMATCH,
                  "Only the teacher named on the acknowledgment row may respond to it")
    ack["ack_status"] = "DECLINED"
    ack["ack_responded_at"] = now()
    touch(ack)
    plan["all_teachers_acknowledged"] = ack_gate_satisfied(plan["id"])
    return success(ack_out(ack), 200)
