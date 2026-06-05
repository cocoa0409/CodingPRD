from flask import Blueprint

import errors
from db import db, now_iso
from middleware import require_roles
from response import success_object, success_array
from services import calc
from services.common import (
    get_json_body, parse_pagination, paginate,
    require_str, opt_bool, require_int_min,
    get_center_or_404,
)
from services.serialize import serialize_center, serialize_parcel

bp = Blueprint("transit_centers", __name__)


@bp.post("/delivery/transit-centers")
@require_roles("DispatchManager")
def create_center():
    body = get_json_body()
    name = require_str(body, "name")
    hazmat = opt_bool(body, "hazmat_certified", False)
    sort_capacity = require_int_min(body, "sort_capacity", 1)
    ts = now_iso()
    cid = db.new_id()
    center = {
        "id": cid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "name": name,
        "hazmat_certified": hazmat,
        "sort_capacity": sort_capacity,
        "sorted_count": 0,
        "status": "OPEN",
    }
    db.transit_centers[cid] = center
    return success_object(serialize_center(center), 201)


@bp.get("/delivery/transit-centers")
@require_roles("DispatchManager", "SortAssociate", "Driver", "CustomerServiceAgent")
def list_centers():
    limit, offset = parse_pagination()
    items = sorted(db.transit_centers.values(), key=lambda c: (c["created_at"], c["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return success_array([serialize_center(c) for c in page], limit, offset, total)


@bp.get("/delivery/transit-centers/<center_id>")
@require_roles("DispatchManager", "SortAssociate", "Driver", "CustomerServiceAgent")
def get_center(center_id):
    center = get_center_or_404(center_id)
    return success_object(serialize_center(center), 200)


@bp.post("/delivery/transit-centers/<center_id>/close")
@require_roles("DispatchManager")
def close_center(center_id):
    center = get_center_or_404(center_id)
    center["status"] = "CLOSED"
    center["updated_at"] = now_iso()
    center["version"] += 1
    return success_object(serialize_center(center), 200)


@bp.get("/delivery/transit-centers/<center_id>/sorted-parcels")
@require_roles("DispatchManager", "SortAssociate")
def list_sorted_parcels(center_id):
    get_center_or_404(center_id)
    limit, offset = parse_pagination()
    items = [p for p in db.parcels.values()
             if p["status"] == "SORTED" and p.get("sorted_at_center_id") == center_id]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return success_array([serialize_parcel(p) for p in page], limit, offset, total)
