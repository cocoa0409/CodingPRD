"""Waves, the allocation waterfall, and pick tasks (PRD §3.7, §3.8, §3.9)."""
from flask import Blueprint, request

from common import (
    new_record, touch, serialize, get_json_body, require_str, require_int,
    require_bool, paginate, lookup, lookup_fk,
)
from db import store
from errors import err
from middleware import get_identity, require_roles
from response import success, list_success
import calc
import services

bp = Blueprint("waves", __name__)


# ---------------------------------------------------------------------------
# Wave
# ---------------------------------------------------------------------------
@bp.route("/warehouse/waves", methods=["POST"])
def create_wave():
    _, role = get_identity()
    require_roles(role, ["WavePlanner"])
    body = get_json_body()
    wave_label = require_str(body, "wave_label")
    if any(w["wave_label"] == wave_label for w in store.waves.values()):
        raise err("ERR_DUPLICATE_CODE", "wave_label already exists.")
    rec = new_record()
    rec.update({
        "wave_label": wave_label,
        "release_status": "PLANNING",
        "fulfillment_status": "UNALLOCATED",
    })
    store.waves[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.route("/warehouse/waves/<wave_id>", methods=["GET"])
def get_wave(wave_id):
    get_identity()
    rec = lookup(store.waves, wave_id)
    return success(serialize(rec))


@bp.route("/warehouse/waves", methods=["GET"])
def list_waves():
    get_identity()
    items = list(store.waves.values())
    release_status = request.args.get("release_status")
    fulfillment_status = request.args.get("fulfillment_status")
    if release_status:
        items = [w for w in items if w["release_status"] == release_status]
    if fulfillment_status:
        items = [w for w in items if w["fulfillment_status"] == fulfillment_status]
    page, limit, offset, total = paginate(items)
    return list_success(page, limit, offset, total)


@bp.route("/warehouse/waves/<wave_id>/add-order", methods=["POST"])
def add_order_to_wave(wave_id):
    _, role = get_identity()
    require_roles(role, ["WavePlanner"])
    wave = lookup(store.waves, wave_id)
    body = get_json_body()
    order_id = require_str(body, "order_id")
    order = lookup_fk(store.outbound_orders, order_id, "order_id")
    # state: wave PLANNING and order OPEN
    if wave["release_status"] != "PLANNING":
        raise err("ERR_INVALID_STATE", "Wave is not in PLANNING.")
    if order["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Order is not OPEN.")
    order["status"] = "WAVED"
    order["wave_id"] = wave_id
    touch(order)
    touch(wave)
    return success(serialize(wave))


def _run_allocation_waterfall(wave):
    """PRD §3.8 — fully deterministic allocation."""
    orders = [o for o in store.outbound_orders.values() if o["wave_id"] == wave["id"]]
    orders.sort(key=lambda o: (o["priority"], o["created_at"], o.get("_seq", 0)))
    affected_lpns = set()
    affected_skus = set()
    for o in orders:
        lines = [l for l in store.order_lines.values() if l["order_id"] == o["id"]]
        lines.sort(key=lambda l: (l["created_at"], l.get("_seq", 0)))
        for line in lines:
            calc.refresh_order_line(line)
            remaining = line["ordered_qty"] - line["allocated_qty"]
            if remaining <= 0:
                continue
            supply = [
                lp for lp in store.license_plates.values()
                if lp["sku_id"] == line["sku_id"]
                and lp["disposition"] == "STORED"
                and calc.lpn_free(lp) > 0
            ]
            supply.sort(key=lambda lp: (lp["created_at"], lp.get("_seq", 0)))
            for lp in supply:
                if remaining == 0:
                    break
                free = calc.lpn_free(lp)
                take = min(free, remaining)
                if take > 0:
                    rec = new_record()
                    rec.update({
                        "order_line_id": line["id"],
                        "lpn_id": lp["id"],
                        "allocated_qty": take,
                        "status": "RESERVED",
                    })
                    store.allocations[rec["id"]] = rec
                    remaining -= take
                    affected_lpns.add(lp["id"])
                    affected_skus.add(lp["sku_id"])
            calc.refresh_order_line(line)
    # drive each fully-reserved LPN STORED -> ALLOCATED
    for lpn_id in affected_lpns:
        services.maybe_flip_lpn_on_reserve(store.license_plates[lpn_id])
    for sku_id in affected_skus:
        calc.refresh_sku(store.skus[sku_id])


@bp.route("/warehouse/waves/<wave_id>/release", methods=["POST"])
def release_wave(wave_id):
    _, role = get_identity()
    require_roles(role, ["WavePlanner"])
    wave = lookup(store.waves, wave_id)
    body = get_json_body()
    expected_wave_version = require_int(body, "expected_wave_version")
    # state (priority 5)
    if wave["release_status"] != "PLANNING":
        raise err("ERR_INVALID_STATE", "Wave is not in PLANNING.")
    # OCC (priority 6)
    if expected_wave_version != wave["version"]:
        raise err("ERR_STALE_WAVE_VERSION", "expected_wave_version does not match the wave version.")
    # cross-entity state (priority 8): wave must hold >= 1 order
    orders = [o for o in store.outbound_orders.values() if o["wave_id"] == wave_id]
    if not orders:
        raise err("ERR_CROSS_ENTITY_STATE", "Wave has no orders to release.")
    _run_allocation_waterfall(wave)
    wave["release_status"] = "RELEASED"
    wave["fulfillment_status"] = "ALLOCATED"
    touch(wave)
    return success(serialize(wave))


@bp.route("/warehouse/waves/<wave_id>/start-picking", methods=["POST"])
def start_picking(wave_id):
    _, role = get_identity()
    require_roles(role, ["WavePlanner"])
    wave = lookup(store.waves, wave_id)
    if wave["fulfillment_status"] != "ALLOCATED" or wave["release_status"] != "RELEASED":
        raise err("ERR_INVALID_STATE", "Wave must be RELEASED/ALLOCATED to start picking.")
    # spawn one PickTask per allocation of this wave
    alloc_ids = []
    for o in store.outbound_orders.values():
        if o["wave_id"] != wave_id:
            continue
        line_ids = {l["id"] for l in store.order_lines.values() if l["order_id"] == o["id"]}
        for a in store.allocations.values():
            if a["order_line_id"] in line_ids and a["status"] in ("RESERVED", "COMMITTED"):
                alloc_ids.append(a)
    alloc_ids.sort(key=lambda a: (a["created_at"], a.get("_seq", 0)))
    for a in alloc_ids:
        task = new_record()
        task.update({
            "wave_id": wave_id,
            "allocation_id": a["id"],
            "light_confirmed": False,
            "status": "PENDING",
        })
        store.pick_tasks[task["id"]] = task
    # drive each WAVED order of this wave -> PICKING
    for o in store.outbound_orders.values():
        if o["wave_id"] == wave_id and o["status"] == "WAVED":
            o["status"] = "PICKING"
            touch(o)
    wave["fulfillment_status"] = "PICKING"
    touch(wave)
    return success(serialize(wave))


@bp.route("/warehouse/waves/<wave_id>/pick-tasks", methods=["GET"])
def list_wave_pick_tasks(wave_id):
    get_identity()
    lookup(store.waves, wave_id)
    items = [t for t in store.pick_tasks.values() if t["wave_id"] == wave_id]
    page, limit, offset, total = paginate(items)
    return list_success(page, limit, offset, total)


# ---------------------------------------------------------------------------
# PickTask
# ---------------------------------------------------------------------------
@bp.route("/warehouse/pick-tasks/<task_id>", methods=["GET"])
def get_pick_task(task_id):
    get_identity()
    rec = lookup(store.pick_tasks, task_id)
    return success(serialize(rec))


@bp.route("/warehouse/pick-tasks", methods=["GET"])
def list_pick_tasks():
    get_identity()
    items = list(store.pick_tasks.values())
    wave_id = request.args.get("wave_id")
    allocation_id = request.args.get("allocation_id")
    status = request.args.get("status")
    if wave_id:
        items = [t for t in items if t["wave_id"] == wave_id]
    if allocation_id:
        items = [t for t in items if t["allocation_id"] == allocation_id]
    if status:
        items = [t for t in items if t["status"] == status]
    page, limit, offset, total = paginate(items)
    return list_success(page, limit, offset, total)


@bp.route("/warehouse/pick-tasks/<task_id>/start", methods=["POST"])
def start_pick(task_id):
    _, role = get_identity()
    require_roles(role, ["Picker"])
    task = lookup(store.pick_tasks, task_id)
    if task["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Pick task is not PENDING.")
    wave = store.waves.get(task["wave_id"])
    # cross-entity state guard (priority 8)
    if wave is None or wave["fulfillment_status"] != "PICKING":
        raise err("ERR_CROSS_ENTITY_STATE", "Parent wave is not in PICKING.")
    task["status"] = "IN_PROGRESS"
    touch(task)
    return success(serialize(task))


@bp.route("/warehouse/pick-tasks/<task_id>/confirm", methods=["POST"])
def confirm_pick(task_id):
    _, role = get_identity()
    require_roles(role, ["Picker"])
    task = lookup(store.pick_tasks, task_id)
    body = get_json_body()
    light_confirmed = require_bool(body, "light_confirmed")
    # state (priority 5)
    if task["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Pick task is not IN_PROGRESS.")
    # light-required business check (priority 16)
    if light_confirmed is not True:
        raise err("ERR_VALIDATION_LIGHT_REQUIRED", "light_confirmed must be true to confirm.")
    alloc = store.allocations.get(task["allocation_id"])
    if alloc is None or alloc["status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "Referenced allocation is not RESERVED.")
    task["light_confirmed"] = True
    # allocation RESERVED -> COMMITTED
    alloc["status"] = "COMMITTED"
    touch(alloc)
    line = store.order_lines.get(alloc["order_line_id"])
    if line is not None:
        calc.refresh_order_line(line)
    # LPN ALLOCATED -> PICKED_STAGED
    lpn = store.license_plates.get(alloc["lpn_id"])
    if lpn is not None and lpn["disposition"] == "ALLOCATED":
        lpn["disposition"] = "PICKED_STAGED"
        touch(lpn)
    task["status"] = "PICKED"
    touch(task)
    # bubble order PICKING -> PICKED
    if line is not None:
        order = store.outbound_orders.get(line["order_id"])
        if order is not None:
            services.maybe_bubble_order_picked(order)
    # bubble wave fulfillment PICKING -> PICKED (and release CLOSED)
    wave = store.waves.get(task["wave_id"])
    if wave is not None:
        services.maybe_bubble_wave_picked(wave)
    return success(serialize(task))


@bp.route("/warehouse/pick-tasks/<task_id>/short", methods=["POST"])
def short_pick(task_id):
    _, role = get_identity()
    require_roles(role, ["Picker"])
    task = lookup(store.pick_tasks, task_id)
    if task["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Pick task is not IN_PROGRESS.")
    alloc = store.allocations.get(task["allocation_id"])
    if alloc is not None and alloc["status"] == "RESERVED":
        services.release_allocation(alloc)
        lpn = store.license_plates.get(alloc["lpn_id"])
        if lpn is not None:
            sku = store.skus.get(lpn["sku_id"])
            if sku is not None:
                calc.refresh_sku(sku)
    task["status"] = "SHORT"
    touch(task)
    return success(serialize(task))


@bp.route("/warehouse/pick-tasks/<task_id>/cancel", methods=["POST"])
def cancel_pick(task_id):
    _, role = get_identity()
    require_roles(role, ["WavePlanner"])
    task = lookup(store.pick_tasks, task_id)
    if task["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Only a PENDING pick task may be cancelled.")
    alloc = store.allocations.get(task["allocation_id"])
    if alloc is not None and alloc["status"] == "RESERVED":
        services.release_allocation(alloc)
        lpn = store.license_plates.get(alloc["lpn_id"])
        if lpn is not None:
            sku = store.skus.get(lpn["sku_id"])
            if sku is not None:
                calc.refresh_sku(sku)
    task["status"] = "CANCELLED"
    touch(task)
    return success(serialize(task))
