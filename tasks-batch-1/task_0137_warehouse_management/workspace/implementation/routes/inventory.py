"""Cycle counts and min/max replenishment (PRD §3.10, §3.11)."""
from flask import Blueprint, request

from common import (
    new_record, touch, serialize, get_json_body, require_str, require_int,
    paginate, lookup, lookup_fk,
)
from db import store
from errors import err
from middleware import get_identity, require_roles
from response import success, list_success
import calc

bp = Blueprint("inventory", __name__)

CC_SNAPSHOT_DISP = {"STORED", "ALLOCATED"}


# ---------------------------------------------------------------------------
# CycleCount
# ---------------------------------------------------------------------------
def _system_qty(location_id, sku_id):
    return sum(
        lp["qty"]
        for lp in store.license_plates.values()
        if lp["location_id"] == location_id
        and lp["sku_id"] == sku_id
        and lp["disposition"] in CC_SNAPSHOT_DISP
    )


@bp.route("/warehouse/cycle-counts", methods=["POST"])
def create_cycle_count():
    _, role = get_identity()
    require_roles(role, ["InventoryController"])
    body = get_json_body()
    location_id = require_str(body, "location_id")
    location = lookup_fk(store.locations, location_id, "location_id")
    sku_id = require_str(body, "sku_id")
    sku = lookup_fk(store.skus, sku_id, "sku_id")
    rec = new_record()
    rec.update({
        "location_id": location["id"],
        "sku_id": sku["id"],
        "system_qty": _system_qty(location["id"], sku["id"]),
        "counted_qty": None,
        "variance_qty": 0,
        "counted_by_user_id": None,
        "status": "OPEN",
    })
    store.cycle_counts[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.route("/warehouse/cycle-counts/<cc_id>", methods=["GET"])
def get_cycle_count(cc_id):
    get_identity()
    rec = lookup(store.cycle_counts, cc_id)
    return success(serialize(rec))


@bp.route("/warehouse/cycle-counts", methods=["GET"])
def list_cycle_counts():
    get_identity()
    items = list(store.cycle_counts.values())
    location_id = request.args.get("location_id")
    sku_id = request.args.get("sku_id")
    status = request.args.get("status")
    if location_id:
        items = [c for c in items if c["location_id"] == location_id]
    if sku_id:
        items = [c for c in items if c["sku_id"] == sku_id]
    if status:
        items = [c for c in items if c["status"] == status]
    page, limit, offset, total = paginate(items)
    return list_success(page, limit, offset, total)


@bp.route("/warehouse/cycle-counts/<cc_id>/submit", methods=["POST"])
def submit_cycle_count(cc_id):
    user_id, role = get_identity()
    require_roles(role, ["InventoryController"])
    cc = lookup(store.cycle_counts, cc_id)
    body = get_json_body()
    counted_qty = require_int(body, "counted_qty", minimum=0)
    if cc["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Cycle count is not OPEN.")
    cc["counted_qty"] = counted_qty
    cc["counted_by_user_id"] = user_id
    cc["variance_qty"] = counted_qty - cc["system_qty"]
    cc["status"] = "COUNTED"
    touch(cc)
    return success(serialize(cc))


def _receivers_feeding_location(location_id):
    """X-User-IDs of ReceivingClerks who received any ASN that fed an LPN at
    this location (PRD §2.9, §3.10)."""
    asn_ids = set()
    for lp in store.license_plates.values():
        if lp["location_id"] == location_id and lp["source_asn_id"]:
            asn_ids.add(lp["source_asn_id"])
    receivers = set()
    for asn_id in asn_ids:
        asn = store.inbound_asns.get(asn_id)
        if asn is not None and asn.get("received_by_user_id"):
            receivers.add(asn["received_by_user_id"])
    return receivers


@bp.route("/warehouse/cycle-counts/<cc_id>/approve", methods=["POST"])
def approve_cycle_count(cc_id):
    user_id, role = get_identity()
    require_roles(role, ["InventoryController"])
    cc = lookup(store.cycle_counts, cc_id)
    if cc["status"] != "COUNTED":
        raise err("ERR_INVALID_STATE", "Cycle count is not COUNTED.")
    # segregation of duties (priority 7)
    if user_id == cc["counted_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "Approver may not be the counter.")
    if user_id in _receivers_feeding_location(cc["location_id"]):
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "Approver received an ASN feeding this location.")
    # apply variance
    if cc["variance_qty"] != 0:
        _apply_variance(cc)
    cc["status"] = "RECONCILED"
    touch(cc)
    sku = store.skus.get(cc["sku_id"])
    if sku is not None:
        calc.refresh_sku(sku)
    return success(serialize(cc))


def _apply_variance(cc):
    """Adjust STORED LPN qty at the location for the SKU by variance, filling
    plates in created_at ASC order (PRD §3.10)."""
    variance = cc["variance_qty"]
    plates = [
        lp for lp in store.license_plates.values()
        if lp["location_id"] == cc["location_id"]
        and lp["sku_id"] == cc["sku_id"]
        and lp["disposition"] == "STORED"
    ]
    plates.sort(key=lambda lp: (lp["created_at"], lp.get("_seq", 0)))
    remaining = variance
    affected_locations = set()
    if remaining > 0:
        # add eaches to the first plate (created_at ASC fill order)
        if plates:
            plates[0]["qty"] += remaining
            touch(plates[0])
            affected_locations.add(plates[0]["location_id"])
    elif remaining < 0:
        deficit = -remaining
        for lp in plates:
            if deficit <= 0:
                break
            take = min(lp["qty"], deficit)
            lp["qty"] -= take
            deficit -= take
            touch(lp)
            affected_locations.add(lp["location_id"])
    for loc_id in affected_locations:
        if loc_id and loc_id in store.locations:
            calc.refresh_location(store.locations[loc_id])
    sku = store.skus.get(cc["sku_id"])
    if sku is not None:
        calc.refresh_sku(sku)


@bp.route("/warehouse/cycle-counts/<cc_id>/reject", methods=["POST"])
def reject_cycle_count(cc_id):
    user_id, role = get_identity()
    require_roles(role, ["InventoryController"])
    cc = lookup(store.cycle_counts, cc_id)
    if cc["status"] != "COUNTED":
        raise err("ERR_INVALID_STATE", "Cycle count is not COUNTED.")
    # segregation of duties (priority 7) — only the submitter constraint on reject
    if user_id == cc["counted_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "Rejecter may not be the counter.")
    cc["status"] = "REJECTED"
    touch(cc)
    return success(serialize(cc))


# ---------------------------------------------------------------------------
# ReplenishmentTask
# ---------------------------------------------------------------------------
def _pick_face_for_sku(sku_id):
    for loc in store.locations.values():
        if loc.get("pick_face_for_sku_id") == sku_id:
            return loc
    return None


def _face_on_hand(location_id, sku_id):
    return sum(
        lp["qty"]
        for lp in store.license_plates.values()
        if lp["location_id"] == location_id
        and lp["sku_id"] == sku_id
        and lp["disposition"] in CC_SNAPSHOT_DISP
    )


@bp.route("/warehouse/replenishment-tasks", methods=["POST"])
def create_replen_task():
    _, role = get_identity()
    require_roles(role, ["InventoryController"])
    body = get_json_body()
    sku_id = require_str(body, "sku_id")
    sku = lookup_fk(store.skus, sku_id, "sku_id")
    pick_face = _pick_face_for_sku(sku["id"])
    if pick_face is None:
        # No declared error for "no pick face"; treat as not-needed eligibility.
        raise err("ERR_REPLEN_NOT_NEEDED", "SKU has no dedicated pick face.")
    face_on_hand = _face_on_hand(pick_face["id"], sku["id"])
    # eligibility (priority 12): face on-hand must be at-or-below min_qty
    if face_on_hand > sku["min_qty"]:
        raise err("ERR_REPLEN_NOT_NEEDED", "Pick face is above the replenishment floor.")
    replen_qty = sku["max_qty"] - face_on_hand
    rec = new_record()
    rec.update({
        "sku_id": sku["id"],
        "pick_face_location_id": pick_face["id"],
        "source_lpn_id": None,
        "replen_qty": replen_qty,
        "status": "CREATED",
    })
    store.replenishment_tasks[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.route("/warehouse/replenishment-tasks/<task_id>", methods=["GET"])
def get_replen_task(task_id):
    get_identity()
    rec = lookup(store.replenishment_tasks, task_id)
    return success(serialize(rec))


@bp.route("/warehouse/replenishment-tasks", methods=["GET"])
def list_replen_tasks():
    get_identity()
    items = list(store.replenishment_tasks.values())
    sku_id = request.args.get("sku_id")
    source_lpn_id = request.args.get("source_lpn_id")
    pick_face_location_id = request.args.get("pick_face_location_id")
    status = request.args.get("status")
    if sku_id:
        items = [t for t in items if t["sku_id"] == sku_id]
    if source_lpn_id:
        items = [t for t in items if t["source_lpn_id"] == source_lpn_id]
    if pick_face_location_id:
        items = [t for t in items if t["pick_face_location_id"] == pick_face_location_id]
    if status:
        items = [t for t in items if t["status"] == status]
    page, limit, offset, total = paginate(items)
    return list_success(page, limit, offset, total)


@bp.route("/warehouse/replenishment-tasks/<task_id>/assign", methods=["POST"])
def assign_replen_task(task_id):
    _, role = get_identity()
    require_roles(role, ["InventoryController"])
    task = lookup(store.replenishment_tasks, task_id)
    if task["status"] != "CREATED":
        raise err("ERR_INVALID_STATE", "Replenishment task is not CREATED.")
    source = calc.replen_source_select(task)
    if source is None:
        raise err("ERR_NO_REPLEN_SOURCE", "No reserve source covering the replenishment quantity.")
    task["source_lpn_id"] = source["id"]
    task["status"] = "ASSIGNED"
    touch(task)
    return success(serialize(task))


@bp.route("/warehouse/replenishment-tasks/<task_id>/complete", methods=["POST"])
def complete_replen_task(task_id):
    _, role = get_identity()
    require_roles(role, ["PutawayOperator"])
    task = lookup(store.replenishment_tasks, task_id)
    if task["status"] != "ASSIGNED":
        raise err("ERR_INVALID_STATE", "Replenishment task is not ASSIGNED.")
    source = store.license_plates.get(task["source_lpn_id"])
    if source is None or source["qty"] < task["replen_qty"]:
        raise err("ERR_INVALID_STATE", "Source LPN does not hold enough quantity.")
    pick_face = store.locations.get(task["pick_face_location_id"])
    sku = store.skus.get(task["sku_id"])
    replen_qty = task["replen_qty"]
    # capacity check against the pick face (priority 10)
    incoming = replen_qty * sku["each_volume_cm3"]
    if calc.location_used_volume(pick_face["id"]) + incoming > pick_face["max_volume_cm3"]:
        raise err("ERR_LOCATION_CAPACITY", "Replenishment would exceed pick-face capacity.")
    source_location_id = source["location_id"]
    # decrement source
    source["qty"] -= replen_qty
    if source["qty"] == 0:
        source["disposition"] = "DEPLETED"
        source["location_id"] = None
    touch(source)
    # add to pick face: mint/merge a PICK_FACE STORED plate
    existing = None
    for lp in store.license_plates.values():
        if (lp["location_id"] == pick_face["id"] and lp["sku_id"] == sku["id"]
                and lp["disposition"] == "STORED"):
            existing = lp
            break
    if existing is not None:
        existing["qty"] += replen_qty
        touch(existing)
    else:
        new_lp = new_record()
        new_lp.update({
            "lpn_code": "LPN-" + new_lp["id"][:8],
            "sku_id": sku["id"],
            "location_id": pick_face["id"],
            "source_asn_id": None,
            "qty": replen_qty,
            "disposition": "STORED",
        })
        store.license_plates[new_lp["id"]] = new_lp
    # recompute volumes and on-hand
    calc.refresh_location(pick_face)
    if source_location_id and source_location_id in store.locations:
        calc.refresh_location(store.locations[source_location_id])
    calc.refresh_sku(sku)
    task["status"] = "COMPLETED"
    touch(task)
    return success(serialize(task))


@bp.route("/warehouse/replenishment-tasks/<task_id>/cancel", methods=["POST"])
def cancel_replen_task(task_id):
    _, role = get_identity()
    require_roles(role, ["InventoryController"])
    task = lookup(store.replenishment_tasks, task_id)
    if task["status"] not in ("CREATED", "ASSIGNED"):
        raise err("ERR_INVALID_STATE", "Replenishment task cannot be cancelled in its current state.")
    if task["status"] == "ASSIGNED":
        task["source_lpn_id"] = None
    task["status"] = "CANCELLED"
    touch(task)
    return success(serialize(task))
