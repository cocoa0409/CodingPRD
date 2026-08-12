"""ComponentAllocation cross-reference endpoints."""
from flask import Blueprint, request

from core import err, list_page, require_roles, success
from services import must_get, release_allocation, serialize_allocation
from store import db

bp = Blueprint("allocations", __name__)

ALLOC_ROLES = ("ProductionPlanner", "QAManager", "PlantDirector")


@bp.get("/cosmfg/allocations/<aid>")
@require_roles(*ALLOC_ROLES)
def get_allocation(aid):
    return success(serialize_allocation(
        must_get(db.allocations, aid, "ComponentAllocation")))


@bp.get("/cosmfg/allocations")
@require_roles(*ALLOC_ROLES)
def list_allocations():
    items = list(db.allocations.values())
    order_id = request.args.get("production_order_id")
    if order_id is not None:
        items = [a for a in items if a["production_order_id"] == order_id]
    batch_id = request.args.get("batch_id")
    if batch_id is not None:
        items = [a for a in items if a.get("batch_id") == batch_id]
    lot_id = request.args.get("lot_id")
    if lot_id is not None:
        items = [a for a in items if a["lot_id"] == lot_id]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_page(items, serialize_allocation)


@bp.post("/cosmfg/allocations/<aid>/release")
@require_roles("ProductionPlanner")
def release_allocation_endpoint(aid):
    a = must_get(db.allocations, aid, "ComponentAllocation")
    if a["status"] != "RESERVED":
        err("ERR_INVALID_STATE", 409, "Only a RESERVED allocation may be released")
    release_allocation(a)
    return success(serialize_allocation(a))
