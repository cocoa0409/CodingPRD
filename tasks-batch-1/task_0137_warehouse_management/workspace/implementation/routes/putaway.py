"""Putaway-task endpoints (PRD §3.4)."""
from flask import Blueprint, request

from common import touch, serialize, paginate, lookup
from db import store
from errors import err
from middleware import get_identity, require_roles
from response import success, list_success
import calc
import services

bp = Blueprint("putaway", __name__)


@bp.route("/warehouse/putaway-tasks/<task_id>", methods=["GET"])
def get_task(task_id):
    get_identity()
    rec = lookup(store.putaway_tasks, task_id)
    return success(serialize(rec))


@bp.route("/warehouse/putaway-tasks", methods=["GET"])
def list_tasks():
    get_identity()
    items = list(store.putaway_tasks.values())
    lpn_id = request.args.get("lpn_id")
    target_location_id = request.args.get("target_location_id")
    status = request.args.get("status")
    if lpn_id:
        items = [t for t in items if t["lpn_id"] == lpn_id]
    if target_location_id:
        items = [t for t in items if t["target_location_id"] == target_location_id]
    if status:
        items = [t for t in items if t["status"] == status]
    page, limit, offset, total = paginate(items)
    return list_success(page, limit, offset, total)


@bp.route("/warehouse/putaway-tasks/<task_id>/assign", methods=["POST"])
def assign_task(task_id):
    _, role = get_identity()
    require_roles(role, ["PutawayOperator"])
    task = lookup(store.putaway_tasks, task_id)
    if task["status"] != "CREATED":
        raise err("ERR_INVALID_STATE", "Putaway task is not CREATED.")
    lpn = store.license_plates.get(task["lpn_id"])
    loc = calc.putaway_location_select(lpn)
    if loc is None:
        raise err("ERR_NO_PUTAWAY_LOCATION", "No eligible putaway location.")
    task["target_location_id"] = loc["id"]
    task["status"] = "ASSIGNED"
    touch(task)
    return success(serialize(task))


@bp.route("/warehouse/putaway-tasks/<task_id>/complete", methods=["POST"])
def complete_task(task_id):
    _, role = get_identity()
    require_roles(role, ["PutawayOperator"])
    task = lookup(store.putaway_tasks, task_id)
    if task["status"] != "ASSIGNED":
        raise err("ERR_INVALID_STATE", "Putaway task is not ASSIGNED.")
    loc = store.locations.get(task["target_location_id"])
    lpn = store.license_plates.get(task["lpn_id"])
    sku = store.skus.get(lpn["sku_id"])
    # cross-entity state guard: target must be AVAILABLE (priority 8)
    if loc is None or loc["status"] != "AVAILABLE":
        raise err("ERR_CROSS_ENTITY_STATE", "Target location is not AVAILABLE.")
    # capacity (priority 10): existing used + incoming volume must fit
    need = lpn["qty"] * sku["each_volume_cm3"]
    if calc.location_used_volume(loc["id"]) + need > loc["max_volume_cm3"]:
        raise err("ERR_LOCATION_CAPACITY", "Move would exceed location capacity.")
    # drive LPN PUTAWAY_PENDING -> STORED
    lpn["location_id"] = loc["id"]
    lpn["disposition"] = "STORED"
    touch(lpn)
    calc.refresh_location(loc)
    calc.refresh_sku(sku)
    task["status"] = "COMPLETED"
    touch(task)
    # maybe bubble the source ASN closed
    if lpn["source_asn_id"]:
        asn = store.inbound_asns.get(lpn["source_asn_id"])
        if asn is not None:
            services.maybe_bubble_asn_closed(asn)
    return success(serialize(task))


@bp.route("/warehouse/putaway-tasks/<task_id>/cancel", methods=["POST"])
def cancel_task(task_id):
    _, role = get_identity()
    require_roles(role, ["PutawayOperator"])
    task = lookup(store.putaway_tasks, task_id)
    if task["status"] not in ("CREATED", "ASSIGNED"):
        raise err("ERR_INVALID_STATE", "Putaway task cannot be cancelled in its current state.")
    if task["status"] == "ASSIGNED":
        task["target_location_id"] = None
    task["status"] = "CANCELLED"
    touch(task)
    return success(serialize(task))
