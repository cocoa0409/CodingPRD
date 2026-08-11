"""HotWorkPermit endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_FIRE_WATCH_INCOMPLETE,
    ERR_FIRE_WATCH_TOO_SHORT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_PERMIT_OVERLAP,
    ERR_PERMIT_WINDOW_INACTIVE,
    ERR_PERMIT_WINDOW_INVALID,
    ERR_POSTURE_STOP_WORK,
    ERR_SOD_VIOLATION,
)
from middleware import require_roles
from response import success_object
from services import calculations as calc
from services.common import (
    get_site_or_404,
    init_common,
    paginate,
    parse_body,
    parse_iso,
    require_fields,
    serialize,
    touch,
    validate_int,
    validate_str,
)

bp = Blueprint("hot_work", __name__)

READ_ROLES = ("SafetyManager", "ComplianceManager", "ComplianceEngineer",
              "HotWorkPerformer", "InspectorUser")


def _get_permit(site_id, permit_id):
    site = get_site_or_404(site_id)
    permit = db.hot_work_permits.get(permit_id)
    if permit is None or permit["site_id"] != site["id"]:
        raise ApiError(ERR_NOT_FOUND, f"HotWorkPermit {permit_id} not found", 404)
    return site, permit


@bp.route("/api/sites/<id>/hot-work-permits", methods=["POST"])
def create_permit(id):
    require_roles("SafetyManager")
    site = get_site_or_404(id)
    body = parse_body()
    require_fields(body, ["work_description", "issuer_id", "performer_id",
                          "valid_from", "valid_to", "fire_watch_minutes_after"])
    validate_str(body, "work_description")
    validate_str(body, "issuer_id")
    validate_str(body, "performer_id")
    validate_int(body, "fire_watch_minutes_after")

    # Optional collector FK
    collector_id = body.get("collector_id")
    if collector_id is not None:
        col = db.collectors.get(collector_id)
        if col is None or col["site_id"] != site["id"]:
            raise ApiError(ERR_NOT_FOUND, f"Collector {collector_id} not found", 404)

    valid_from = parse_iso(body["valid_from"], "valid_from")
    valid_to = parse_iso(body["valid_to"], "valid_to")

    # Window validity
    if not (valid_to > valid_from) or valid_to > valid_from + timedelta(hours=24):
        raise ApiError(ERR_PERMIT_WINDOW_INVALID, "Permit window is invalid", 422)
    if body["fire_watch_minutes_after"] < 30:
        raise ApiError(ERR_FIRE_WATCH_TOO_SHORT, "fire_watch_minutes_after must be >= 30", 422)

    permit = {
        "site_id": site["id"],
        "collector_id": collector_id,
        "work_description": body["work_description"],
        "issuer_id": body["issuer_id"],
        "performer_id": body["performer_id"],
        "valid_from": db.iso(valid_from),
        "valid_from_dt": valid_from,
        "valid_to": db.iso(valid_to),
        "valid_to_dt": valid_to,
        "fire_watch_minutes_after": body["fire_watch_minutes_after"],
        "status": "ISSUED",
    }
    init_common(permit)
    db.hot_work_permits[permit["id"]] = permit
    return success_object(serialize(permit), 201)


@bp.route("/api/sites/<id>/hot-work-permits", methods=["GET"])
def list_permits(id):
    require_roles(*READ_ROLES)
    site = get_site_or_404(id)
    items = [p for p in db.hot_work_permits.values() if p["site_id"] == site["id"]]
    filters = {}
    if request.args.get("status") is not None:
        filters["status"] = "status"
    if request.args.get("collector_id") is not None:
        filters["collector_id"] = "collector_id"
    return paginate(items, filters)


@bp.route("/api/sites/<id>/hot-work-permits/<permit_id>", methods=["GET"])
def get_permit(id, permit_id):
    require_roles(*READ_ROLES)
    _, permit = _get_permit(id, permit_id)
    return success_object(serialize(permit), 200)


@bp.route("/api/sites/<id>/hot-work-permits/<permit_id>/start", methods=["POST"])
def start_permit(id, permit_id):
    user_id, _ = require_roles("HotWorkPerformer")
    site, permit = _get_permit(id, permit_id)
    if permit["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, "Permit is not ISSUED", 409)
    if site["posture"] == "STOP_WORK":
        raise ApiError(ERR_POSTURE_STOP_WORK, "Site is in STOP_WORK posture", 409)
    if permit["performer_id"] != user_id:
        raise ApiError(ERR_SOD_VIOLATION, "Only the designated performer may start work", 422)

    now = db.now_dt()
    vf = permit["valid_from_dt"]
    vt = permit["valid_to_dt"]
    if not (vf <= now < vt):
        raise ApiError(ERR_PERMIT_WINDOW_INACTIVE, "Permit window is not active", 422)

    if permit.get("collector_id"):
        col = db.collectors.get(permit["collector_id"])
        if col is not None and col["status"] == "DECOMMISSIONED":
            raise ApiError(ERR_INVALID_STATE, "Referenced collector is decommissioned", 409)

    for other in db.hot_work_permits.values():
        if other["id"] == permit["id"]:
            continue
        if other["site_id"] != site["id"] or other["status"] != "IN_PROGRESS":
            continue
        ovf, ovt = other["valid_from_dt"], other["valid_to_dt"]
        if vf < ovt and ovf < vt:
            raise ApiError(ERR_PERMIT_OVERLAP, "Another permit is in progress with overlapping window", 422)

    permit["status"] = "IN_PROGRESS"
    touch(permit)
    site["hot_work_in_progress"] = int(site.get("hot_work_in_progress", 0)) + 1
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(permit), 200)


@bp.route("/api/sites/<id>/hot-work-permits/<permit_id>/close", methods=["POST"])
def close_permit(id, permit_id):
    user_id, _ = require_roles("HotWorkPerformer")
    site, permit = _get_permit(id, permit_id)
    if permit["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, "Permit is not IN_PROGRESS", 409)
    if permit["performer_id"] != user_id:
        raise ApiError(ERR_SOD_VIOLATION, "Only the designated performer may close", 422)
    now = db.now_dt()
    ready = permit["valid_to_dt"] + timedelta(minutes=permit["fire_watch_minutes_after"])
    if now < ready:
        raise ApiError(ERR_FIRE_WATCH_INCOMPLETE, "Fire watch period has not fully elapsed", 422)

    permit["status"] = "CLOSED"
    touch(permit)
    site["hot_work_in_progress"] = max(0, int(site.get("hot_work_in_progress", 0)) - 1)
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(permit), 200)


@bp.route("/api/sites/<id>/hot-work-permits/<permit_id>/void", methods=["POST"])
def void_permit(id, permit_id):
    user_id, _ = require_roles("SafetyManager")
    site, permit = _get_permit(id, permit_id)
    if permit["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, "Permit is not ISSUED", 409)
    if permit["issuer_id"] != user_id:
        raise ApiError(ERR_SOD_VIOLATION, "Only the issuer may void the permit", 422)
    permit["status"] = "VOIDED"
    touch(permit)
    return success_object(serialize(permit), 200)
