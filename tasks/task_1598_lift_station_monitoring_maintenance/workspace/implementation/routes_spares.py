"""SparePump routes: register/list/get and the reserve-deploy-return pool
lifecycle (PRD 3.4)."""
from flask import Blueprint, request

import db
from envelope import success
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_DUPLICATE_ASSET_TAG,
    ERR_ZONE_MISMATCH,
)
from helpers import body, bad, is_int, req_str, paginate, ASSET_TAG_RE
from middleware import require_roles
from serializers import ser_spare

bp = Blueprint("spare_pumps", __name__)

SPARE_READ_ROLES = ("UtilityAdmin", "OperationsSupervisor", "MaintenancePlanner")


def get_spare_or_404(sid):
    s = db.spare_pumps.get(sid)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Spare pump not found")
    return s


@bp.post("/spare-pumps")
def create_spare():
    require_roles("UtilityAdmin", "MaintenancePlanner")
    b = body()
    # business constraint (priority 16): format + uniqueness
    tag = b.get("asset_tag")
    if tag is not None:
        if not isinstance(tag, str) or not ASSET_TAG_RE.match(tag):
            raise ApiError(
                ERR_DUPLICATE_ASSET_TAG, 422,
                "asset_tag must match ^SP-[0-9]{4}$",
            )
        for s in db.spare_pumps.values():
            if s["asset_tag"] == tag:
                raise ApiError(
                    ERR_DUPLICATE_ASSET_TAG, 422,
                    "asset_tag %s already exists" % tag,
                )
    # shape (priority 30)
    if tag is None:
        bad("asset_tag is required")
    rated = b.get("rated_gpm")
    if not is_int(rated) or rated <= 0:
        bad("rated_gpm must be a positive integer")
    zone = req_str(b, "compatible_zone")
    s = {
        "id": db.new_id(),
        "asset_tag": tag,
        "rated_gpm": rated,
        "compatible_zone": zone,
        "status": "AVAILABLE",
        "reserved_for_station_id": None,
        "deployed_at_station_id": None,
    }
    db.stamp(s)
    db.spare_pumps[s["id"]] = s
    return success(ser_spare(s), 201)


@bp.get("/spare-pumps")
def list_spares():
    require_roles(*SPARE_READ_ROLES)
    items = list(db.spare_pumps.values())
    for field in ("status", "compatible_zone", "reserved_for_station_id",
                  "deployed_at_station_id"):
        v = request.args.get(field)
        if v is not None:
            items = [s for s in items if s[field] == v]
    page, meta = paginate(items)
    return success([ser_spare(s) for s in page], 200, meta)


@bp.get("/spare-pumps/<sid>")
def get_spare(sid):
    require_roles(*SPARE_READ_ROLES)
    return success(ser_spare(get_spare_or_404(sid)))


# --------------------------------------------------------------------- lifecycle


@bp.post("/spare-pumps/<sid>/reserve")
def reserve_spare(sid):
    require_roles("MaintenancePlanner")
    s = get_spare_or_404(sid)
    if s["status"] != "AVAILABLE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an AVAILABLE spare can be reserved")
    b = body()
    station_id = b.get("station_id")
    if station_id is None:
        bad("station_id is required")
    if not isinstance(station_id, str):
        bad("station_id must be a string")
    st = db.stations.get(station_id)
    if st is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422, "station_id does not resolve")
    # business constraint (priority 17): zone compatibility
    if s["compatible_zone"] != st["service_zone"]:
        raise ApiError(
            ERR_ZONE_MISMATCH, 422,
            "Spare's compatible_zone does not match the station's service_zone",
        )
    s["reserved_for_station_id"] = station_id
    s["status"] = "RESERVED"
    db.touch(s)
    return success(ser_spare(s))


@bp.post("/spare-pumps/<sid>/deploy")
def deploy_spare(sid):
    require_roles("MaintenancePlanner")
    s = get_spare_or_404(sid)
    if s["status"] != "RESERVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a RESERVED spare can be deployed")
    s["deployed_at_station_id"] = s["reserved_for_station_id"]
    s["reserved_for_station_id"] = None
    s["status"] = "DEPLOYED"
    db.touch(s)
    return success(ser_spare(s))


@bp.post("/spare-pumps/<sid>/return")
def return_spare(sid):
    require_roles("MaintenancePlanner")
    s = get_spare_or_404(sid)
    if s["status"] not in ("DEPLOYED", "REBUILD"):
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only a DEPLOYED or REBUILD spare can be returned",
        )
    s["deployed_at_station_id"] = None
    s["status"] = "AVAILABLE"
    db.touch(s)
    return success(ser_spare(s))


@bp.post("/spare-pumps/<sid>/release")
def release_spare(sid):
    require_roles("MaintenancePlanner")
    s = get_spare_or_404(sid)
    if s["status"] != "RESERVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a RESERVED spare can be released")
    s["reserved_for_station_id"] = None
    s["status"] = "AVAILABLE"
    db.touch(s)
    return success(ser_spare(s))


@bp.post("/spare-pumps/<sid>/send-to-rebuild")
def send_spare_to_rebuild(sid):
    require_roles("MaintenancePlanner")
    s = get_spare_or_404(sid)
    if s["status"] != "AVAILABLE":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Only an AVAILABLE spare can be sent to rebuild"
        )
    s["status"] = "REBUILD"
    db.touch(s)
    return success(ser_spare(s))


@bp.post("/spare-pumps/<sid>/retire")
def retire_spare(sid):
    require_roles("UtilityAdmin")
    s = get_spare_or_404(sid)
    if s["status"] != "AVAILABLE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an AVAILABLE spare can be retired")
    s["status"] = "RETIRED"
    db.touch(s)
    return success(ser_spare(s))
