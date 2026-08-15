"""Finished lot endpoints: packing, shipping, cold-chain logging."""

from datetime import timedelta
from flask import Blueprint, request

from db import store, new_id, iso_format, parse_iso
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from validation import get_body, req_string, req_number, req_int
from errors import (raise_error, ERR_NOT_FOUND, ERR_DAY_NOT_OPEN,
                    ERR_LABEL_INVALID_STATE, ERR_POSITIVE_PATHOGEN_UNRESOLVED,
                    ERR_LABEL_VERSION_STALE, ERR_COOLER_CAPACITY_EXCEEDED,
                    ERR_FINISHED_LOT_INVALID_STATE, ERR_SHELF_LIFE_EXPIRED)
from serializers import finished_lot_out
from services import touch, recompute_cooler, recompute_shelf_life, round2

bp = Blueprint("finished_lots", __name__)

READ_ROLES = ("PlantAdmin", "QAManager", "QATech", "LabAnalyst", "Inspector", "ProductionManager")


def _get_finished_lot(fl_id):
    fl = store.finished_lots.get(fl_id)
    if not fl:
        raise_error(ERR_NOT_FOUND, "Finished lot not found")
    return fl


@bp.route("/production-days/<did>/finished-lots", methods=["POST"])
def create_finished_lot(did):
    user_id, _ = require_roles("ProductionManager")
    body = get_body()
    source_lot_id = req_string(body, "source_lot_id")
    label_approval_id = req_string(body, "label_approval_id")
    units_produced = req_int(body, "units_produced", gt=0)
    unit_weight_lbs = req_number(body, "unit_weight_lbs", gt=0)
    shelf_life_days = req_int(body, "shelf_life_days", gt=0)

    day = store.production_days.get(did)
    if not day:
        raise_error(ERR_NOT_FOUND, "Production day not found")
    # State family first: day must be OPEN
    if day["status"] != "OPEN":
        raise_error(ERR_DAY_NOT_OPEN, "Production day is not OPEN")

    # Resolve references
    source_lot = store.carcass_lots.get(source_lot_id)
    if not source_lot:
        raise_error(ERR_NOT_FOUND, "Source carcass lot not found")
    label = store.label_approvals.get(label_approval_id)
    if not label:
        raise_error(ERR_NOT_FOUND, "Label approval not found")

    # Business checks in PRD §3.8 order:
    # 1. label must be APPROVED
    if label["status"] != "APPROVED":
        raise_error(ERR_LABEL_INVALID_STATE, "Label approval is not APPROVED")
    # 2. source lot must be FABRICATED (implicit in "pack finished product from a FABRICATED lot")
    if source_lot["status"] != "FABRICATED":
        from errors import ERR_LOT_INVALID_STATE
        raise_error(ERR_LOT_INVALID_STATE, "Source lot must be FABRICATED")
    # 3. no pathogen sample of the source lot may be PENDING or POSITIVE
    for s in store.pathogen_samples.values():
        if s["lot_id"] == source_lot_id and s["result"] in ("PENDING", "POSITIVE"):
            raise_error(ERR_POSITIVE_PATHOGEN_UNRESOLVED,
                        "Source lot has a PENDING or POSITIVE pathogen sample")
    # 4. label must be the latest-approved for (plant, product_name)
    plant_id = day["plant_id"]
    same_name_approved = [
        l for l in store.label_approvals.values()
        if l["plant_id"] == plant_id and l["product_name"] == label["product_name"] and l["status"] == "APPROVED"
    ]
    # The latest-approved is the one whose updated_at (mutation at approve) is newest; use created+version ordering.
    # We track an approval sequence by updated_at.
    if same_name_approved:
        latest = max(same_name_approved, key=lambda l: (l["updated_at"], l["id"]))
        if latest["id"] != label["id"]:
            raise_error(ERR_LABEL_VERSION_STALE,
                        "Label is not the latest-approved for this product name")
    # 5. Cooler gate
    total_weight = round2(units_produced * unit_weight_lbs)
    plant = store.plants[plant_id]
    if plant["cooler_occupied_lbs"] + total_weight > plant["cooler_capacity_lbs"]:
        raise_error(ERR_COOLER_CAPACITY_EXCEEDED, "Cooler capacity would be exceeded")

    now = store.now_iso()
    now_dt = store.now()
    base_use_by = now_dt + timedelta(days=shelf_life_days)
    fl = {
        "id": new_id(),
        "production_day_id": did,
        "source_lot_id": source_lot_id,
        "label_approval_id": label_approval_id,
        "units_produced": units_produced,
        "unit_weight_lbs": unit_weight_lbs,
        "total_weight_lbs": total_weight,
        "production_date": now,
        "shelf_life_days": shelf_life_days,
        "base_use_by_at": iso_format(base_use_by),
        "penalty_hours": 0,
        "use_by_at": iso_format(base_use_by),
        "temperature_logs": [],
        "status": "PRODUCED",
        "shipped_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.finished_lots[fl["id"]] = fl
    recompute_cooler(plant_id)
    return success_object(finished_lot_out(fl), 201)


@bp.route("/finished-lots/<fid>", methods=["GET"])
def get_finished_lot(fid):
    require_roles(*READ_ROLES)
    return success_object(finished_lot_out(_get_finished_lot(fid)))


@bp.route("/finished-lots", methods=["GET"])
def list_finished_lots():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    day_id = request.args.get("production_day_id")
    source_lot_id = request.args.get("source_lot_id")
    label_approval_id = request.args.get("label_approval_id")
    status = request.args.get("status")
    items = sorted(store.finished_lots.values(), key=lambda f: (f["created_at"], f["id"]))
    if day_id is not None:
        items = [f for f in items if f["production_day_id"] == day_id]
    if source_lot_id is not None:
        items = [f for f in items if f["source_lot_id"] == source_lot_id]
    if label_approval_id is not None:
        items = [f for f in items if f["label_approval_id"] == label_approval_id]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([finished_lot_out(f) for f in page], limit, offset, total)


@bp.route("/finished-lots/<fid>/ship", methods=["POST"])
def ship_finished_lot(fid):
    user_id, _ = require_roles("ProductionManager")
    get_body()
    fl = _get_finished_lot(fid)
    if fl["status"] != "PRODUCED":
        raise_error(ERR_FINISHED_LOT_INVALID_STATE, "Finished lot must be PRODUCED to ship")
    # Inclusive temporal gate: now <= use_by_at
    now = store.now()
    use_by = parse_iso(fl["use_by_at"])
    if now > use_by:
        raise_error(ERR_SHELF_LIFE_EXPIRED, "Logical clock is strictly after use_by_at")
    fl["status"] = "SHIPPED"
    fl["shipped_at"] = store.now_iso()
    touch(fl)
    day = store.production_days[fl["production_day_id"]]
    recompute_cooler(day["plant_id"])
    return success_object(finished_lot_out(fl))


@bp.route("/finished-lots/<fid>/log-temperature", methods=["POST"])
def log_temperature(fid):
    user_id, _ = require_roles("ProductionManager")
    body = get_body()
    temp_f = req_number(body, "temp_f")
    fl = _get_finished_lot(fid)
    if fl["status"] not in ("PRODUCED", "QUARANTINED"):
        raise_error(ERR_FINISHED_LOT_INVALID_STATE,
                    "Finished lot must be PRODUCED or QUARANTINED to log temperature")
    fl["temperature_logs"].append({
        "recorded_at": store.now_iso(),
        "temp_f": temp_f,
    })
    use_by = recompute_shelf_life(fl)
    now = store.now()
    # Auto-spoil when use_by_at has passed (strictly before now)
    if use_by < now and fl["status"] == "PRODUCED":
        fl["status"] = "SPOILED"
    touch(fl)
    day = store.production_days[fl["production_day_id"]]
    recompute_cooler(day["plant_id"])
    return success_object(finished_lot_out(fl))
