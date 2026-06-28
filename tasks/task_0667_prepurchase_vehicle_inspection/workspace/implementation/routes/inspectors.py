"""Inspector endpoints (PRD §3.1)."""
from flask import Blueprint, g, request

from db import db, stamp_create, touch
from errors import err
from helpers import (check_enum, get_json_body, paginate, parse_pagination,
                     require_fields, serialize, sort_by_created)
from middleware import require_roles
from response import success
from services.lookups import get_inspector

bp = Blueprint("inspectors", __name__)

TIER_CODES = {"STANDARD", "PREMIUM", "HEAVY_DUTY"}
INSPECTOR_STATUSES = {"AVAILABLE", "OFFLINE"}


def serialize_inspector(insp):
    return serialize(insp)


@bp.route("/inspectors", methods=["POST"])
@require_roles("OpsAdmin")
def create_inspector():
    body = get_json_body()
    require_fields(body, ["full_name", "base_lat", "base_lng", "certified_tiers"])

    base_lat = body["base_lat"]
    base_lng = body["base_lng"]
    if not isinstance(base_lat, (int, float)) or isinstance(base_lat, bool):
        raise err("ERR_INVALID_REQUEST", "base_lat must be numeric")
    if not isinstance(base_lng, (int, float)) or isinstance(base_lng, bool):
        raise err("ERR_INVALID_REQUEST", "base_lng must be numeric")

    tiers = body["certified_tiers"]
    if not isinstance(tiers, list) or len(tiers) == 0:
        raise err("ERR_INVALID_REQUEST", "certified_tiers must be a non-empty array")
    for t in tiers:
        check_enum(t, TIER_CODES, "certified_tiers")

    max_daily = body.get("max_daily_jobs", 3)
    if max_daily is None:
        max_daily = 3
    if not isinstance(max_daily, int) or isinstance(max_daily, bool) or max_daily < 0:
        raise err("ERR_INVALID_REQUEST", "max_daily_jobs must be a non-negative integer")

    insp = {
        "full_name": body["full_name"],
        "base_lat": base_lat,
        "base_lng": base_lng,
        "certified_tiers": list(tiers),
        "max_daily_jobs": max_daily,
        "status": "AVAILABLE",
    }
    stamp_create(insp)
    db.inspectors[insp["id"]] = insp
    return success(serialize_inspector(insp), status=201)


@bp.route("/inspectors/<inspector_id>", methods=["GET"])
@require_roles("OpsAdmin", "Inspector")
def get_inspector_ep(inspector_id):
    insp = get_inspector(inspector_id)
    return success(serialize_inspector(insp), status=200)


@bp.route("/inspectors/<inspector_id>/set-status", methods=["POST"])
@require_roles("OpsAdmin", "Inspector")
def set_inspector_status(inspector_id):
    insp = get_inspector(inspector_id)
    body = get_json_body()
    require_fields(body, ["status"])
    check_enum(body["status"], INSPECTOR_STATUSES, "status")
    insp["status"] = body["status"]
    touch(insp)
    return success(serialize_inspector(insp), status=200)


@bp.route("/inspectors/<inspector_id>/assignments", methods=["GET"])
@require_roles("OpsAdmin", "Inspector")
def list_inspector_assignments(inspector_id):
    from routes.assignments import serialize_assignment
    get_inspector(inspector_id)
    limit, offset = parse_pagination()
    items = [a for a in db.assignments.values() if a["inspector_id"] == inspector_id]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([serialize_assignment(a) for a in page], status=200, pagination=meta)
