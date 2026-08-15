"""WetWellCleaning routes: schedule/list/get, start/complete/cancel (PRD 3.6)."""
from flask import Blueprint, request

import db
import services
from envelope import success
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_PERMIT_REQUIRED,
    ERR_GREASE_DEPTH_INVALID,
)
from helpers import (
    body, bad, req_instant, req_bool, to_decimal, paginate,
)
from middleware import require_roles
from routes_stations import get_station_or_404
from serializers import ser_cleaning

bp = Blueprint("wet_well_cleanings", __name__)

CLEANING_READ_ROLES = (
    "UtilityAdmin", "OperationsSupervisor", "Operator", "MaintenancePlanner",
)


def get_cleaning_or_404(cid):
    c = db.wet_well_cleanings.get(cid)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Wet-well cleaning not found")
    return c


@bp.post("/stations/<sid>/wet-well-cleanings")
def create_cleaning(sid):
    require_roles("MaintenancePlanner", "OperationsSupervisor")
    st = get_station_or_404(sid)
    b = body()
    # body FK existence (priority 5)
    crew = b.get("crew_lead_operator_id")
    if crew is None:
        bad("crew_lead_operator_id is required")
    if not isinstance(crew, str):
        bad("crew_lead_operator_id must be a string")
    if crew not in db.operators:
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND, 422,
            "crew_lead_operator_id does not resolve",
        )
    # posture gate (priority 7)
    services.check_posture(st)
    # shape (priority 30)
    scheduled = req_instant(b, "scheduled_for")
    pre = b.get("grease_depth_inches_pre")
    if pre is None:
        bad("grease_depth_inches_pre is required")
    pre = to_decimal(pre, "grease_depth_inches_pre", 1)
    if pre < 0:
        bad("grease_depth_inches_pre must be >= 0")
    requires_cse = req_bool(b, "requires_confined_space_entry")
    c = {
        "id": db.new_id(),
        "station_id": sid,
        "scheduled_for": scheduled,
        "status": "SCHEDULED",
        "completed_at": None,
        "grease_depth_inches_pre": pre,
        "grease_depth_inches_post": None,
        "crew_lead_operator_id": crew,
        "requires_confined_space_entry": requires_cse,
    }
    db.stamp(c)
    db.wet_well_cleanings[c["id"]] = c
    return success(ser_cleaning(c), 201)


@bp.get("/stations/<sid>/wet-well-cleanings")
def list_station_cleanings(sid):
    require_roles(*CLEANING_READ_ROLES)
    get_station_or_404(sid)
    items = [c for c in db.wet_well_cleanings.values() if c["station_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return success([ser_cleaning(c) for c in page], 200, meta)


@bp.get("/wet-well-cleanings")
def list_cleanings():
    require_roles(*CLEANING_READ_ROLES)
    items = list(db.wet_well_cleanings.values())
    stid = request.args.get("station_id")
    if stid is not None:
        items = [c for c in items if c["station_id"] == stid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    crew = request.args.get("crew_lead_operator_id")
    if crew is not None:
        items = [c for c in items if c["crew_lead_operator_id"] == crew]
    page, meta = paginate(items)
    return success([ser_cleaning(c) for c in page], 200, meta)


@bp.get("/wet-well-cleanings/<cid>")
def get_cleaning(cid):
    require_roles(*CLEANING_READ_ROLES)
    return success(ser_cleaning(get_cleaning_or_404(cid)))


# --------------------------------------------------------------------- lifecycle


@bp.post("/wet-well-cleanings/<cid>/start")
def start_cleaning(cid):
    require_roles("Operator")
    c = get_cleaning_or_404(cid)
    st = db.stations[c["station_id"]]
    if c["status"] not in ("SCHEDULED", "OVERDUE"):
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only a SCHEDULED or OVERDUE cleaning can be started",
        )
    services.check_posture(st)
    # referential (priority 23): confined-space entry needs a live permit
    if c["requires_confined_space_entry"]:
        ok = any(
            p["station_id"] == st["id"] and p["status"] in ("ISSUED", "ACTIVE")
            for p in db.confined_space_permits.values()
        )
        if not ok:
            raise ApiError(
                ERR_PERMIT_REQUIRED, 422,
                "Cleaning requires an ISSUED or ACTIVE confined-space permit",
            )
    c["status"] = "IN_PROGRESS"
    db.touch(c)
    return success(ser_cleaning(c))


@bp.post("/wet-well-cleanings/<cid>/complete")
def complete_cleaning(cid):
    require_roles("Operator")
    c = get_cleaning_or_404(cid)
    st = db.stations[c["station_id"]]
    if c["status"] not in ("IN_PROGRESS", "OVERDUE"):
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only an IN_PROGRESS or OVERDUE cleaning can be completed",
        )
    services.check_posture(st)
    # temporal (priority 20): post depth must be strictly below the pre depth
    b = body()
    post_raw = b.get("grease_depth_inches_post")
    if post_raw is None:
        bad("grease_depth_inches_post is required")
    post = to_decimal(post_raw, "grease_depth_inches_post", 1)
    if post < 0:
        bad("grease_depth_inches_post must be >= 0")
    if post >= c["grease_depth_inches_pre"]:
        raise ApiError(
            ERR_GREASE_DEPTH_INVALID, 422,
            "grease_depth_inches_post must be less than grease_depth_inches_pre",
        )
    c["grease_depth_inches_post"] = post
    c["completed_at"] = db.now()
    c["status"] = "COMPLETED"
    db.touch(c)
    return success(ser_cleaning(c))


@bp.post("/wet-well-cleanings/<cid>/cancel")
def cancel_cleaning(cid):
    require_roles("OperationsSupervisor")
    c = get_cleaning_or_404(cid)
    st = db.stations[c["station_id"]]
    if c["status"] not in ("SCHEDULED", "OVERDUE"):
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only a SCHEDULED or OVERDUE cleaning can be cancelled",
        )
    services.check_posture(st)
    c["status"] = "CANCELLED"
    db.touch(c)
    return success(ser_cleaning(c))
