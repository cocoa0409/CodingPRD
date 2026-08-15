"""FiberLot endpoints."""

from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import err_not_found
from middleware import require_roles
from response import success_list, success_object
from serializers import serialize_blend_component, serialize_fiber_lot
from services.workflows import components_of_fiber_lot
from validators import (
    apply_filters,
    get_pagination,
    get_json_body,
    req_decimal,
    req_enum,
    round2,
    round4,
    sort_and_paginate,
)

bp = Blueprint("fiber_lots", __name__)

FIBER_TYPES = {"COTTON", "POLYESTER", "RAYON", "WOOL", "NYLON"}
ALL_ROLES = ("MillPlanner", "SpinningSupervisor", "DyeHouseOperator", "QualityInspector", "CustomerServiceRep")


@bp.post("/mill/fiber-lots")
def create_fiber_lot():
    require_roles("MillPlanner")
    body = get_json_body()
    fiber_type = req_enum(body, "fiber_type", FIBER_TYPES)
    received = req_decimal(body, "received_weight_lbs", min_value=0, min_exclusive=True)
    unit_cost = req_decimal(body, "unit_cost_per_lb", min_value=0)
    ts = now_iso()
    record = {
        "id": new_id(),
        "fiber_type": fiber_type,
        "received_weight_lbs": round2(received),
        "available_weight_lbs": round2(received),
        "unit_cost_per_lb": round4(unit_cost),
        "status": "RECEIVED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.fiber_lots[record["id"]] = record
    return success_object(serialize_fiber_lot(record), 201)


@bp.get("/mill/fiber-lots")
def list_fiber_lots():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = apply_filters(
        list(db.fiber_lots.values()),
        {"status": request.args.get("status"), "fiber_type": request.args.get("fiber_type")},
    )
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([serialize_fiber_lot(r) for r in page], limit, offset, total)


@bp.get("/mill/fiber-lots/<fid>")
def get_fiber_lot(fid):
    require_roles(*ALL_ROLES)
    record = db.fiber_lots.get(fid)
    if record is None:
        raise err_not_found("Fiber lot not found")
    return success_object(serialize_fiber_lot(record))


@bp.get("/mill/fiber-lots/<fid>/blend-components")
def list_fiber_lot_components(fid):
    require_roles(*ALL_ROLES)
    record = db.fiber_lots.get(fid)
    if record is None:
        raise err_not_found("Fiber lot not found")
    comps = components_of_fiber_lot(fid)
    comps = sorted(comps, key=lambda c: (c["created_at"], c["id"]))
    return success_list([serialize_blend_component(c) for c in comps], len(comps), 0, len(comps))
