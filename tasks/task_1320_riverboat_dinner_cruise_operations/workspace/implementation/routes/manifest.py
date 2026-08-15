"""Boarding manifest: read (array of 0 or 1), freeze, amend."""
from flask import Blueprint

import db
from errors import ApiError, err_invalid_state
from response import ok
from serializers import serialize as _sz, serialize_list as _szl
from services import core as svc
from util import require_auth, get_or_404, touch, paginate

bp = Blueprint("manifest", __name__)

CAPTAIN = ["Captain"]


@bp.get("/cruises/<cid>/manifest")
def get_manifest(cid):
    require_auth(["OperationsManager", "Captain"])
    cruise = get_or_404(db.cruises, cid, "cruise", "Cruise not found")
    manifest = svc.manifest_for_cruise(cruise["id"])
    items = [manifest] if manifest is not None else []
    page, meta = paginate(items)
    return ok(_szl("manifest", page), pagination=meta)


@bp.post("/cruises/<cid>/manifest/freeze")
def freeze_manifest(cid):
    require_auth(CAPTAIN)
    cruise = get_or_404(db.cruises, cid, "cruise", "Cruise not found")
    manifest = svc.manifest_for_cruise(cruise["id"])
    if manifest is None:
        from errors import NOT_FOUND_IDS, err_not_found
        raise err_not_found(NOT_FOUND_IDS["manifest"], "Boarding manifest not found for cruise")
    if manifest["status"] != "DRAFT":
        raise err_invalid_state("Manifest is not DRAFT")
    if manifest["passenger_count"] > manifest["coast_guard_capacity"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", 409,
                       "passenger_count exceeds coast_guard_capacity snapshot")
    # Freeze holds the current count as a snapshot
    count = 0
    for p in db.passengers.values():
        b = db.bookings.get(p["booking_id"])
        if b is not None and b["cruise_id"] == cruise["id"] and p["boarded_at"] is not None:
            count += 1
    manifest["passenger_count"] = count
    manifest["status"] = "FROZEN"
    touch(manifest)
    return ok(_sz("manifest", manifest))


@bp.post("/cruises/<cid>/manifest/amend")
def amend_manifest(cid):
    require_auth(CAPTAIN)
    cruise = get_or_404(db.cruises, cid, "cruise", "Cruise not found")
    manifest = svc.manifest_for_cruise(cruise["id"])
    if manifest is None:
        from errors import NOT_FOUND_IDS, err_not_found
        raise err_not_found(NOT_FOUND_IDS["manifest"], "Boarding manifest not found for cruise")
    if manifest["status"] != "FROZEN":
        raise err_invalid_state("Manifest is not FROZEN")
    if cruise["status"] != "SCHEDULED":
        raise err_invalid_state("Cruise is not SCHEDULED")
    manifest["status"] = "DRAFT"
    touch(manifest)
    return ok(_sz("manifest", manifest))
