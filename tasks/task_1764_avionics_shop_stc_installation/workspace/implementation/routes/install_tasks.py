"""Install task endpoints: creation, technician start/complete, inspector
verify (segregation of duties), and void."""
from flask import Blueprint, request

import db
import errors
from db import touch
from middleware import (
    authenticate,
    body,
    pagination_args,
    paginate,
    req_enum,
    req_num,
    req_str,
    require_role,
)
from response import success
from serializers import ser_install_task
from services.core import labor_billing, recompute_work_order

bp = Blueprint("install_tasks", __name__)

TASK_KINDS = {"HARNESS_FABRICATION", "PANEL_ASSEMBLY", "INSTALLATION"}
WORKABLE_WO_STATES = ("APPROVED", "PARTS_PENDING", "INSTALLATION")


def _get_task(installTaskId):
    t = db.install_tasks.get(installTaskId)
    if t is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "Install task not found")
    return t


def _check_parent_workable(t):
    wo = db.work_orders[t.work_order_id]
    if wo.status not in WORKABLE_WO_STATES:
        errors.raise_err(
            errors.ERR_INVALID_STATE,
            "Parent work order must be APPROVED, PARTS_PENDING, or INSTALLATION",
        )
    return wo


@bp.post("/avionics/install-tasks")
def create_install_task():
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    b = body()
    work_order_id = req_str(b, "work_order_id")
    task_kind = req_enum(b, "task_kind", TASK_KINDS)
    description = req_str(b, "description")
    estimated_hours = req_num(b, "estimated_hours")
    if not (estimated_hours > 0):
        errors.raise_err(errors.ERR_VALIDATION, "estimated_hours must be greater than 0")

    wo = db.work_orders.get(work_order_id)
    if wo is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "Work order not found")
    if wo.status not in WORKABLE_WO_STATES:
        errors.raise_err(
            errors.ERR_INVALID_STATE,
            "Work order must be APPROVED, PARTS_PENDING, or INSTALLATION",
        )

    t = db.new_entity(
        work_order_id=wo.id,
        task_kind=task_kind,
        description=description,
        estimated_hours=estimated_hours,
        actual_hours=None,
        performed_by_user_id=None,
        verified_by_user_id=None,
        billed_labor_cents=None,
        status="PLANNED",
    )
    db.install_tasks[t.id] = t
    recompute_work_order(wo)
    return success(ser_install_task(t), 201)


@bp.get("/avionics/install-tasks/<installTaskId>")
def get_install_task(installTaskId):
    authenticate()
    return success(ser_install_task(_get_task(installTaskId)), 200)


@bp.get("/avionics/install-tasks")
def list_install_tasks():
    authenticate()
    limit, offset = pagination_args()
    work_order_id = request.args.get("work_order_id")
    status = request.args.get("status")
    items = sorted(db.install_tasks.values(), key=lambda t: t._seq)
    if work_order_id is not None:
        items = [t for t in items if t.work_order_id == work_order_id]
    if status is not None:
        items = [t for t in items if t.status == status]
    page, meta = paginate([ser_install_task(t) for t in items], limit, offset)
    return success(page, 200, meta)


@bp.post("/avionics/install-tasks/<installTaskId>/start")
def start_task(installTaskId):
    _, role = authenticate()
    require_role(role, {"Technician"})
    t = _get_task(installTaskId)
    if t.status != "PLANNED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Only a PLANNED task can be started")
    _check_parent_workable(t)
    t.status = "IN_PROGRESS"
    touch(t)
    return success(ser_install_task(t), 200)


@bp.post("/avionics/install-tasks/<installTaskId>/complete")
def complete_task(installTaskId):
    uid, role = authenticate()
    require_role(role, {"Technician"})
    b = body()
    actual_hours = req_num(b, "actual_hours")
    t = _get_task(installTaskId)
    if t.status != "IN_PROGRESS":
        errors.raise_err(errors.ERR_INVALID_STATE, "Only an IN_PROGRESS task can be completed")
    wo = _check_parent_workable(t)
    # actual_hours replaces any prior figure (rework re-completion)
    t.actual_hours = actual_hours
    t.performed_by_user_id = uid
    t.status = "COMPLETED"
    touch(t)
    recompute_work_order(wo)
    return success(ser_install_task(t), 200)


@bp.post("/avionics/install-tasks/<installTaskId>/verify")
def verify_task(installTaskId):
    uid, role = authenticate()
    require_role(role, {"Inspector"})
    t = _get_task(installTaskId)
    if t.status != "COMPLETED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Only a COMPLETED task can be verified")
    # segregation of duties (priority 6a): never verify your own work
    if uid == t.performed_by_user_id:
        errors.raise_err(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "Inspector may not verify work they performed",
        )
    t.verified_by_user_id = uid
    t.billed_labor_cents = labor_billing(t)
    t.status = "VERIFIED"
    touch(t)
    recompute_work_order(db.work_orders[t.work_order_id])
    return success(ser_install_task(t), 200)


@bp.post("/avionics/install-tasks/<installTaskId>/void")
def void_task(installTaskId):
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    t = _get_task(installTaskId)
    if t.status not in ("PLANNED", "IN_PROGRESS", "COMPLETED"):
        errors.raise_err(
            errors.ERR_INVALID_STATE,
            "Only a PLANNED, IN_PROGRESS, or COMPLETED task can be voided",
        )
    t.status = "VOIDED"
    touch(t)
    recompute_work_order(db.work_orders[t.work_order_id])
    return success(ser_install_task(t), 200)
