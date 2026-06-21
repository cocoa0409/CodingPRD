"""SparePart routes (PRD §3.1, §4)."""
from flask import Blueprint

import db
import errors
import serialize
from middleware import authenticate, authorize, get_json_body
from helpers import require_str, require_int, opt_int, parse_pagination, paginate
from response import object_response, array_response

bp = Blueprint("spare_parts", __name__)


@bp.post("/spare-parts")
def create_spare_part():
    _, role = authenticate()
    authorize(role, ["InventoryClerk", "MaintenanceManager"])
    body = get_json_body()
    sku = require_str(body, "sku")
    name = require_str(body, "name")
    on_hand = require_int(body, "on_hand_qty", minimum=0)
    unit_cost = require_int(body, "unit_cost_cents", minimum=0)
    reorder = opt_int(body, "reorder_point", default=0, minimum=0)
    with db.LOCK:
        # SKU uniqueness (PRD §3.1, validation priority 18) — exact, case-sensitive.
        for p in db.spare_parts.values():
            if p["sku"] == sku:
                raise errors.ApiError(errors.ERR_DUPLICATE_SKU,
                                      "A spare part with this sku already exists.", 409)
        rec = db.new_record()
        rec.update({
            "sku": sku,
            "name": name,
            "on_hand_qty": on_hand,
            "reserved_qty": 0,
            "unit_cost_cents": unit_cost,
            "reorder_point": reorder,
        })
        db.spare_parts[rec["id"]] = rec
        return object_response(serialize.spare_part(rec), 201)


@bp.get("/spare-parts/<pid>")
def get_spare_part(pid):
    _, role = authenticate()
    authorize(role, ["InventoryClerk", "MaintenanceManager", "Planner"])
    with db.LOCK:
        rec = db.spare_parts.get(pid)
        if rec is None:
            raise errors.not_found()
        return object_response(serialize.spare_part(rec), 200)


@bp.get("/spare-parts")
def list_spare_parts():
    _, role = authenticate()
    authorize(role, ["InventoryClerk", "MaintenanceManager", "Planner"])
    limit, offset = parse_pagination()
    with db.LOCK:
        items = sorted(db.spare_parts.values(), key=lambda r: r["_seq"])
        total = len(items)
        page = paginate(items, limit, offset)
        return array_response([serialize.spare_part(r) for r in page], limit, offset, total)
