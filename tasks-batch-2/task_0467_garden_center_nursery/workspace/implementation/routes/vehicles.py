"""Vehicle endpoints + vehicle-scoped delivery list."""
from flask import Blueprint, request

from db import db, base_versioned
from lookups import body, get_nursery, get_vehicle
from middleware import require_roles, parse_pagination, paginate
from response import ok, created, ok_list
from validation import req_str, req_enum, req_int_gt, opt_int

bp = Blueprint("vehicles", __name__)

VEHICLE_TYPES = {"FLATBED", "BOX_TRUCK"}


def vehicle_view(v):
    return {
        "id": v["id"],
        "nursery_id": v["nursery_id"],
        "label": v["label"],
        "vehicle_type": v["vehicle_type"],
        "capacity_cubic_yards": v["capacity_cubic_yards"],
        "turnaround_minutes": v["turnaround_minutes"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


@bp.post("/nurseries/<nursery_id>/vehicles")
@require_roles("InventoryManager")
def create_vehicle(nursery_id):
    get_nursery(nursery_id)
    data = body()
    label = req_str(data, "label")
    vtype = req_enum(data, "vehicle_type", VEHICLE_TYPES)
    capacity = req_int_gt(data, "capacity_cubic_yards", 0)
    turnaround = opt_int(data, "turnaround_minutes", 0)
    if turnaround < 0:
        from errors import err
        import errors as e
        err(e.ERR_INVALID_REQUEST, "turnaround_minutes must be >= 0")

    v = base_versioned()
    v.update({
        "nursery_id": nursery_id,
        "label": label,
        "vehicle_type": vtype,
        "capacity_cubic_yards": capacity,
        "turnaround_minutes": turnaround,
    })
    db.vehicles[v["id"]] = v
    return created(vehicle_view(v))


@bp.get("/nurseries/<nursery_id>/vehicles")
@require_roles("InventoryManager", "SalesClerk")
def list_vehicles(nursery_id):
    get_nursery(nursery_id)
    limit, offset = parse_pagination()
    vtype = request.args.get("vehicle_type")
    items = [v for v in db.vehicles.values() if v["nursery_id"] == nursery_id]
    if vtype is not None:
        items = [v for v in items if v["vehicle_type"] == vtype]
    items.sort(key=lambda v: v["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([vehicle_view(v) for v in page], limit, offset, total)


@bp.get("/vehicles/<vehicle_id>")
@require_roles("InventoryManager", "SalesClerk")
def read_vehicle(vehicle_id):
    v = get_vehicle(vehicle_id)
    return ok(vehicle_view(v))


@bp.get("/vehicles/<vehicle_id>/deliveries")
@require_roles("InventoryManager", "SalesClerk")
def list_vehicle_deliveries(vehicle_id):
    get_vehicle(vehicle_id)
    limit, offset = parse_pagination()
    from routes.deliveries import delivery_view
    status = request.args.get("status")
    items = [d for d in db.deliveries.values() if d["vehicle_id"] == vehicle_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda d: d["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([delivery_view(d) for d in page], limit, offset, total)
