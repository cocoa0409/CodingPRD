"""WorkOrder routes (register, list, get, patch + classify/dispatch/reject/pause/resume/resolve/reopen/close)."""

from flask import Blueprint, request, jsonify

from errors import AppError, ERR_DUPLICATE_LINKED, ERROR_STATUS
import db
import response as resp
import clock
from middleware import require_auth, require_role
from services import work_orders as svc
from services import work_order_calc as calc

bp = Blueprint("work_orders", __name__)


@bp.before_request
def auth():
    require_auth()


@bp.route("/work-orders", methods=["POST"])
def register_call():
    require_role("HotlineOperator")
    body = request.get_json(force=True, silent=True) or {}
    with db.LOCK:
        wo = svc.register_work_order(body)
    if wo.get("duplicate_of_id"):
        # ERR_DUPLICATE_LINKED 409, message embeds the linked work-order id.
        msg = f"Duplicate call linked to existing work order {wo['duplicate_of_id']}"
        # Per scaffold/PRD, the linked row is persisted; the response signals duplicate via 409 ERR_DUPLICATE_LINKED.
        return resp.error(ERR_DUPLICATE_LINKED, msg, ERROR_STATUS[ERR_DUPLICATE_LINKED])
    return resp.success(wo, 201)


@bp.route("/work-orders", methods=["GET"])
def list_work_orders():
    require_role("PlatformAdmin", "Dispatcher", "Supervisor", "DepartmentHandler")
    limit, offset = resp.parse_pagination()
    with db.LOCK:
        rows, total = svc.list_work_orders(
            limit, offset,
            status=request.args.get("status"),
            lead_department_id=request.args.get("lead_department_id"),
            jurisdiction_code=request.args.get("jurisdiction_code"),
            category_code=request.args.get("category_code"),
            period_start=request.args.get("period_start"),
            period_end=request.args.get("period_end"),
        )
        # Recompute warning_state on read.
        for r in rows:
            r["warning_state"] = calc.compute_warning_state(r)
    return resp.success_list(rows, total, limit, offset)


@bp.route("/work-orders/<wo_id>", methods=["GET"])
def get_work_order(wo_id):
    require_role("PlatformAdmin", "Dispatcher", "Supervisor", "DepartmentHandler", "HotlineOperator")
    with db.LOCK:
        wo = svc.get_work_order(wo_id)
        wo["warning_state"] = calc.compute_warning_state(wo)
    return resp.success(wo)


@bp.route("/work-orders/<wo_id>", methods=["PATCH"])
def patch_work_order(wo_id):
    require_role("HotlineOperator")
    with db.LOCK:
        wo = svc.patch_work_order(wo_id, request.get_json(force=True, silent=True) or {})
    return resp.success(wo)


@bp.route("/work-orders/<wo_id>/classify", methods=["POST"])
def classify(wo_id):
    require_role("Dispatcher")
    with db.LOCK:
        wo = svc.classify(wo_id, request.get_json(force=True, silent=True) or {})
    return resp.success(wo)


@bp.route("/work-orders/<wo_id>/dispatch", methods=["POST"])
def dispatch(wo_id):
    require_role("Dispatcher")
    with db.LOCK:
        wo = svc.dispatch(wo_id)
    return resp.success(wo)


@bp.route("/work-orders/<wo_id>/reject", methods=["POST"])
def reject(wo_id):
    require_role("Dispatcher")
    with db.LOCK:
        wo = svc.reject_classification(wo_id, request.get_json(force=True, silent=True) or {})
    return resp.success(wo)


@bp.route("/work-orders/<wo_id>/pause", methods=["POST"])
def pause(wo_id):
    require_role("DepartmentHandler")
    with db.LOCK:
        wo = svc.pause_work_order(wo_id, request.get_json(force=True, silent=True) or {})
    return resp.success(wo)


@bp.route("/work-orders/<wo_id>/resume", methods=["POST"])
def resume(wo_id):
    require_role("DepartmentHandler")
    with db.LOCK:
        wo = svc.resume_work_order(wo_id)
    return resp.success(wo)


@bp.route("/work-orders/<wo_id>/resolve", methods=["POST"])
def resolve(wo_id):
    require_role("DepartmentHandler")
    with db.LOCK:
        wo = svc.resolve(wo_id, request.get_json(force=True, silent=True) or {})
    return resp.success(wo)


@bp.route("/work-orders/<wo_id>/reopen", methods=["POST"])
def reopen(wo_id):
    require_role("HotlineOperator")
    with db.LOCK:
        wo = svc.reopen(wo_id)
    return resp.success(wo)


@bp.route("/work-orders/<wo_id>/close", methods=["POST"])
def close(wo_id):
    require_role("Dispatcher")
    with db.LOCK:
        wo = svc.close(wo_id)
    return resp.success(wo)
