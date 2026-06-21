"""LockerUnit endpoints."""
from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import err
from response import success, list_response
from middleware import require_roles
from common import (get_json, require_fields, require_str, require_enum, fk_or_404,
                    get_or_404, touch, parse_pagination, paginate)
import constants as C
import serializers as S

bp = Blueprint("lockers", __name__)


@bp.post("/locker-units")
def create_locker():
    require_roles("FacilityOperator")
    body = get_json()
    require_fields(body, ["facility_id", "label", "size_tier"])
    facility_id = require_str(body, "facility_id")
    label = require_str(body, "label")
    size_tier = require_enum(body, "size_tier", C.LOCKER_SIZE_TIERS)
    facility = fk_or_404(db.facilities, facility_id)
    # Uniqueness within facility (label).
    for l in db.locker_units.values():
        if l["facility_id"] == facility_id and l["label"] == label:
            raise err("ERR_DUPLICATE", "Locker label already exists in facility")
    lid = new_id()
    locker = {
        "id": lid,
        "facility_id": facility_id,
        "label": label,
        "size_tier": size_tier,
        "status": "AVAILABLE",
        "current_package_id": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.locker_units[lid] = locker
    touch(facility)  # locker counts shifted
    return success(S.locker_out(locker), status=201)


@bp.get("/locker-units/<lid>")
def get_locker(lid):
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    locker = get_or_404(db.locker_units, lid)
    return success(S.locker_out(locker))


@bp.get("/locker-units")
def list_lockers():
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    limit, offset = parse_pagination()
    items = list(db.locker_units.values())
    fid = request.args.get("facility_id")
    status = request.args.get("status")
    size_tier = request.args.get("size_tier")
    cpid = request.args.get("current_package_id")
    if fid is not None:
        items = [x for x in items if x["facility_id"] == fid]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    if size_tier is not None:
        items = [x for x in items if x["size_tier"] == size_tier]
    if cpid is not None:
        items = [x for x in items if x.get("current_package_id") == cpid]
    page, total = paginate(items, limit, offset)
    return list_response([S.locker_out(x) for x in page], limit, offset, total)


@bp.post("/locker-units/<lid>/out-of-service")
def locker_oos(lid):
    require_roles("FacilityOperator")
    locker = get_or_404(db.locker_units, lid)
    if locker["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "Locker must be AVAILABLE to take out of service")
    locker["status"] = "OUT_OF_SERVICE"
    locker["current_package_id"] = None
    touch(locker)
    touch(db.facilities[locker["facility_id"]])
    return success(S.locker_out(locker))


@bp.post("/locker-units/<lid>/restore")
def locker_restore(lid):
    require_roles("FacilityOperator")
    locker = get_or_404(db.locker_units, lid)
    if locker["status"] != "OUT_OF_SERVICE":
        raise err("ERR_INVALID_STATE", "Locker must be OUT_OF_SERVICE to restore")
    locker["status"] = "AVAILABLE"
    touch(locker)
    touch(db.facilities[locker["facility_id"]])
    return success(S.locker_out(locker))
