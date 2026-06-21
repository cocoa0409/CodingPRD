from flask import Blueprint

import errors
from errors import ApiError
from db import db, now_iso
from middleware import require_roles
from response import success_object, success_array
from services import calc
from services.common import (
    get_json_body, parse_pagination, paginate,
    require_str, opt_bool, require_number_positive, opt_enum,
    get_parcel_or_404, get_center_or_404,
)
from services.serialize import serialize_parcel

bp = Blueprint("parcels", __name__)

SERVICE_LEVELS = {"GROUND", "EXPRESS", "PRIORITY"}
HAZMAT_CLASSES = {"NONE", "CLASS_3", "CLASS_8"}


@bp.post("/delivery/parcels")
@require_roles("SortAssociate", "DispatchManager")
def create_parcel():
    body = get_json_body()
    tracking_code = require_str(body, "tracking_code")
    weight = require_number_positive(body, "weight_kg")
    service_level = opt_enum(body, "service_level", SERVICE_LEVELS, "GROUND")
    signature_required = opt_bool(body, "signature_required", False)
    hazmat_class = opt_enum(body, "hazmat_class", HAZMAT_CLASSES, "NONE")
    driver_release = opt_bool(body, "driver_release_authorized", False)

    # uniqueness check (priority 5, after type/range validation)
    for p in db.parcels.values():
        if p["tracking_code"] == tracking_code:
            raise ApiError(errors.ERR_DUPLICATE_TRACKING_CODE, 409, "tracking_code already exists.")

    ts = now_iso()
    pid = db.new_id()
    parcel = {
        "id": pid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "tracking_code": tracking_code,
        "weight_kg": weight,
        "service_level": service_level,
        "signature_required": signature_required,
        "hazmat_class": hazmat_class,
        "driver_release_authorized": driver_release,
        "sorted_at_center_id": None,
        "status": "RECEIVED",
    }
    db.parcels[pid] = parcel
    return success_object(serialize_parcel(parcel), 201)


@bp.get("/delivery/parcels")
@require_roles("DispatchManager", "SortAssociate", "CustomerServiceAgent")
def list_parcels():
    limit, offset = parse_pagination()
    from flask import request
    filter_center = request.args.get("sorted_at_center_id")
    items = list(db.parcels.values())
    if filter_center is not None:
        items = [p for p in items if p.get("sorted_at_center_id") == filter_center]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return success_array([serialize_parcel(p) for p in page], limit, offset, total)


@bp.get("/delivery/parcels/<parcel_id>")
@require_roles("DispatchManager", "SortAssociate", "Driver", "CustomerServiceAgent")
def get_parcel(parcel_id):
    parcel = get_parcel_or_404(parcel_id)
    return success_object(serialize_parcel(parcel), 200)


@bp.post("/delivery/parcels/<parcel_id>/sort")
@require_roles("SortAssociate")
def sort_parcel(parcel_id):
    parcel = get_parcel_or_404(parcel_id)
    body = get_json_body()
    center_id = require_str(body, "center_id")
    # body FK existence (after path existence)
    center = get_center_or_404(center_id)

    # state precondition
    if parcel["status"] != "RECEIVED":
        raise ApiError(errors.ERR_PARCEL_NOT_RECEIVED, 409, "Parcel not in RECEIVED state.")
    # center open
    if center["status"] != "OPEN":
        raise ApiError(errors.ERR_CENTER_CLOSED, 409, "Transit center is closed.")
    # hazmat certification
    if parcel["hazmat_class"] != "NONE" and not center["hazmat_certified"]:
        raise ApiError(errors.ERR_HAZMAT_HUB_NOT_CERTIFIED, 409, "Center not hazmat certified.")
    # capacity
    if calc.center_live_sorted_count(center["id"]) >= center["sort_capacity"]:
        raise ApiError(errors.ERR_SORT_CAPACITY_EXCEEDED, 409, "Center at sort capacity.")

    parcel["status"] = "SORTED"
    parcel["sorted_at_center_id"] = center["id"]
    parcel["updated_at"] = now_iso()
    parcel["version"] += 1

    calc.recompute_center_sorted_count(center)
    center["updated_at"] = now_iso()
    center["version"] += 1

    return success_object(serialize_parcel(parcel), 200)
