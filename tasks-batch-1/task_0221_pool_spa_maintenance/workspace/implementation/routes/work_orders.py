"""WorkOrder endpoints (PRD §3.9)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_identity, require_roles
from response import success, success_list
from services import calculations
from services.common import (
    new_record,
    optional_str,
    paginate,
    require_enum,
    require_int,
    require_json_object,
    require_str,
    serialize,
    sort_by_created,
    touch,
)
from services.derived import recompute_open_work_order_count
from services.lookup import get_pool_or_404, get_visit_or_404, get_work_order_or_404

bp = Blueprint("work_orders", __name__)

COMPONENTS = {"PUMP", "FILTER", "HEATER", "CHLORINATOR", "LINER"}
SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}


def _serialize_wo(wo):
    out = serialize(wo)
    out["repair_total_cents"] = wo["repair_total_cents"]
    return out


def _require_pool_owner(wo):
    """Business-referential ownership (priority 4): acting Customer must own the
    pool the work order references."""
    user_id, role = get_identity()
    pool = db.pools.get(wo["pool_id"])
    if pool is None or pool["customer_id"] != user_id:
        raise err("ERR_NOT_POOL_OWNER", "Acting customer does not own the referenced pool")


@bp.post("/work-orders")
@require_roles("FieldTechnician", "RouteManager")
def create_work_order():
    with db.lock:
        body = require_json_object(request.get_json(silent=True))
        pool_id = require_str(body, "pool_id")
        component = require_enum(body, "component", COMPONENTS)
        severity = require_enum(body, "severity", SEVERITIES)
        raised_by_visit_id = optional_str(body, "raised_by_visit_id")
        pool = get_pool_or_404(pool_id)
        if raised_by_visit_id is not None:
            get_visit_or_404(raised_by_visit_id)
        rec = new_record(
            {
                "pool_id": pool_id,
                "raised_by_visit_id": raised_by_visit_id,
                "component": component,
                "severity": severity,
                "quoted_parts_cents": 0,
                "labor_minutes": 0,
                "status": "OPEN",
                "repair_total_cents": 0,
            }
        )
        db.work_orders[rec["id"]] = rec
        recompute_open_work_order_count(pool)
        return success(_serialize_wo(rec), 201)


@bp.get("/work-orders/<wo_id>")
@require_roles("AccountManager", "RouteManager", "FieldTechnician", "Customer")
def get_work_order(wo_id):
    with db.lock:
        wo = get_work_order_or_404(wo_id)
        return success(_serialize_wo(wo), 200)


@bp.get("/work-orders")
@require_roles("AccountManager", "RouteManager", "FieldTechnician", "Customer")
def list_work_orders():
    with db.lock:
        limit, offset = paginate(request.args)
        items = list(db.work_orders.values())
        for key in ("pool_id", "raised_by_visit_id"):
            val = request.args.get(key)
            if val is not None:
                items = [w for w in items if w.get(key) == val]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([_serialize_wo(w) for w in page], limit, offset, total)


@bp.post("/work-orders/<wo_id>/diagnose")
@require_roles("FieldTechnician")
def diagnose_work_order(wo_id):
    with db.lock:
        wo = get_work_order_or_404(wo_id)
        if wo["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "Work order cannot be diagnosed from its current state")
        body = require_json_object(request.get_json(silent=True))
        quoted_parts_cents = require_int(body, "quoted_parts_cents", minimum=0)
        labor_minutes = require_int(body, "labor_minutes", minimum=0)
        wo["status"] = "DIAGNOSED"
        wo["quoted_parts_cents"] = quoted_parts_cents
        wo["labor_minutes"] = labor_minutes
        touch(wo)
        recompute_open_work_order_count(db.pools[wo["pool_id"]])
        return success(_serialize_wo(wo), 200)


@bp.post("/work-orders/<wo_id>/submit-for-approval")
@require_roles("FieldTechnician")
def submit_for_approval(wo_id):
    with db.lock:
        wo = get_work_order_or_404(wo_id)
        if wo["status"] != "DIAGNOSED":
            raise err("ERR_INVALID_STATE", "Work order cannot be submitted from its current state")
        wo["status"] = "AWAITING_APPROVAL"
        touch(wo)
        return success(_serialize_wo(wo), 200)


@bp.post("/work-orders/<wo_id>/hold")
@require_roles("Customer")
def hold_work_order(wo_id):
    with db.lock:
        wo = get_work_order_or_404(wo_id)
        # Ownership (priority 4) before state (priority 5).
        _require_pool_owner(wo)
        if wo["status"] != "AWAITING_APPROVAL":
            raise err("ERR_INVALID_STATE", "Work order cannot be held from its current state")
        wo["status"] = "ON_HOLD"
        touch(wo)
        return success(_serialize_wo(wo), 200)


@bp.post("/work-orders/<wo_id>/re-diagnose")
@require_roles("FieldTechnician")
def re_diagnose_work_order(wo_id):
    with db.lock:
        wo = get_work_order_or_404(wo_id)
        if wo["status"] != "ON_HOLD":
            raise err("ERR_INVALID_STATE", "Work order cannot be re-diagnosed from its current state")
        body = require_json_object(request.get_json(silent=True))
        quoted_parts_cents = require_int(body, "quoted_parts_cents", minimum=0)
        labor_minutes = require_int(body, "labor_minutes", minimum=0)
        wo["status"] = "DIAGNOSED"
        wo["quoted_parts_cents"] = quoted_parts_cents
        wo["labor_minutes"] = labor_minutes
        touch(wo)
        return success(_serialize_wo(wo), 200)


@bp.post("/work-orders/<wo_id>/resolve")
@require_roles("Customer")
def resolve_work_order(wo_id):
    with db.lock:
        wo = get_work_order_or_404(wo_id)
        # Ownership (priority 4) before state (priority 5).
        _require_pool_owner(wo)
        if wo["status"] != "AWAITING_APPROVAL":
            raise err("ERR_INVALID_STATE", "Work order cannot be resolved from its current state")
        wo["status"] = "RESOLVED"
        wo["repair_total_cents"] = calculations.repair_total(
            labor_minutes=wo["labor_minutes"],
            severity=wo["severity"],
            quoted_parts_cents=wo["quoted_parts_cents"],
        )
        touch(wo)
        recompute_open_work_order_count(db.pools[wo["pool_id"]])
        return success(_serialize_wo(wo), 200)


@bp.post("/work-orders/<wo_id>/cancel")
@require_roles("RouteManager")
def cancel_work_order(wo_id):
    with db.lock:
        wo = get_work_order_or_404(wo_id)
        if wo["status"] not in ("OPEN", "ON_HOLD"):
            raise err("ERR_INVALID_STATE", "Work order cannot be cancelled from its current state")
        wo["status"] = "CANCELLED"
        touch(wo)
        recompute_open_work_order_count(db.pools[wo["pool_id"]])
        return success(_serialize_wo(wo), 200)
