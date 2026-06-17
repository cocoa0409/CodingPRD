"""ProductionTask endpoints (PRD §3.6, §2.9)."""
from flask import Blueprint

import errors
import validate
from db import db
from middleware import get_auth, require_role
from response import ok_array, ok_object
from services import domain
from routes.orders import find_order_or_404, assert_customer_owns_order

bp = Blueprint("production_tasks", __name__)


def _find_task_or_404(task_id):
    t = db.production_tasks.get(task_id)
    if t is None:
        errors.raise_err(errors.ERR_TASK_NOT_FOUND, "ProductionTask not found")
    return t


def _find_workbench_or_404(workbench_id):
    w = db.workbenches.get(workbench_id)
    if w is None:
        errors.raise_err(errors.ERR_WORKBENCH_NOT_FOUND, "Workbench not found")
    return w


def _overlaps_half_open(s1, e1, s2, e2):
    # half-open [s,e): overlap iff s1 < e2 and s2 < e1
    return s1 < e2 and s2 < e1


def _gap_too_small(new_s, new_e, ex_s, ex_e, buffer_min):
    """For glass-cutting benches: if intervals overlap -> conflict; else the
    gap between them must be >= buffer. Abutting (gap 0) conflicts when buffer>0.
    """
    if _overlaps_half_open(new_s, new_e, ex_s, ex_e):
        return True
    if new_s >= ex_e:
        gap = new_s - ex_e
    else:  # new_e <= ex_s
        gap = ex_s - new_e
    return gap < buffer_min


@bp.route("/production-tasks", methods=["POST"])
def create_task():
    auth = get_auth()
    require_role(auth, ("FrameProductionTech",))
    body = validate.get_json_body()

    # existence: order first, then workbench (left-to-right body refs)
    order_id = validate.require(body, "order_id")
    if not isinstance(order_id, str) or order_id.strip() == "":
        errors.raise_err(errors.ERR_INVALID_REQUEST, "order_id must be a string")
    workbench_id = validate.require(body, "workbench_id")
    if not isinstance(workbench_id, str) or workbench_id.strip() == "":
        errors.raise_err(errors.ERR_INVALID_REQUEST, "workbench_id must be a string")

    order = find_order_or_404(order_id)
    workbench = _find_workbench_or_404(workbench_id)

    # request well-formedness for interval
    start_minute = validate.require(body, "start_minute")
    end_minute = validate.require(body, "end_minute")
    if isinstance(start_minute, bool) or not isinstance(start_minute, int) or start_minute < 0:
        errors.raise_err(errors.ERR_INVALID_REQUEST, "start_minute must be an integer >= 0")
    if isinstance(end_minute, bool) or not isinstance(end_minute, int) or end_minute <= start_minute:
        errors.raise_err(errors.ERR_INVALID_REQUEST, "end_minute must be an integer > start_minute")

    # priority 8: fragile -> glass bench
    if order["has_fragile_line"] and workbench["bench_type"] != "GLASS_CUTTING":
        errors.raise_err(
            errors.ERR_FRAGILE_REQUIRES_GLASS_BENCH, "Fragile order requires a glass-cutting bench"
        )

    # priority 9: interval availability against SCHEDULED/COMPLETED tasks on same bench
    existing = [
        t
        for t in db.production_tasks.values()
        if t["workbench_id"] == workbench_id and t["task_status"] in ("SCHEDULED", "COMPLETED")
    ]
    is_glass = workbench["bench_type"] == "GLASS_CUTTING"
    buffer_min = workbench["clean_buffer_minutes"]
    for t in existing:
        if is_glass:
            if _gap_too_small(start_minute, end_minute, t["start_minute"], t["end_minute"], buffer_min):
                errors.raise_err(errors.ERR_WORKBENCH_CONFLICT, "Workbench interval conflict")
        else:
            if _overlaps_half_open(start_minute, end_minute, t["start_minute"], t["end_minute"]):
                errors.raise_err(errors.ERR_WORKBENCH_CONFLICT, "Workbench interval conflict")

    t = {
        "order_id": order_id,
        "workbench_id": workbench_id,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "task_status": "SCHEDULED",
    }
    domain.stamp_create(t)
    db.production_tasks[t["id"]] = t
    return ok_object(domain.serialize_task(t), status=201)


@bp.route("/framing-orders/<order_id>/production-tasks", methods=["GET"])
def list_order_tasks(order_id):
    auth = get_auth()
    require_role(auth, ("FrameProductionTech", "FrameDesigner", "FrontDeskClerk", "Customer"))
    o = find_order_or_404(order_id)
    assert_customer_owns_order(auth, o)
    limit, offset = validate.parse_pagination()
    items = domain.order_tasks(order_id)
    items.sort(key=lambda t: (t["created_at"], t["id"]))
    page, total = validate.paginate(items, limit, offset)
    return ok_array([domain.serialize_task(t) for t in page], limit, offset, total)


@bp.route("/production-tasks/<task_id>", methods=["GET"])
def get_task(task_id):
    auth = get_auth()
    require_role(auth, ("FrameProductionTech", "FrameDesigner", "FrontDeskClerk"))
    t = _find_task_or_404(task_id)
    return ok_object(domain.serialize_task(t))


@bp.route("/production-tasks/<task_id>/complete", methods=["POST"])
def complete_task(task_id):
    auth = get_auth()
    require_role(auth, ("FrameProductionTech",))
    t = _find_task_or_404(task_id)

    o = db.framing_orders.get(t["order_id"])
    if o is None or o["production_status"] != "IN_PRODUCTION":
        errors.raise_err(errors.ERR_ORDER_NOT_IN_PRODUCTION, "Order not in production")

    if t["task_status"] != "SCHEDULED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Task is not SCHEDULED")

    t["task_status"] = "COMPLETED"
    domain.touch(t)
    return ok_object(domain.serialize_task(t))
