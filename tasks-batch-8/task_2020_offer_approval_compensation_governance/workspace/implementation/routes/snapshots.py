"""InternalEquitySnapshot endpoints."""

from flask import Blueprint, request

import db
from errors import raise_err, ERR_SNAPSHOT_NOT_FOUND
from middleware import (
    get_actor, require_role, get_json_body, validate_fields, req_enum, req_int,
    req_number, get_pagination, paginate,
)
from response import success

bp = Blueprint("snapshots", __name__)

ROLE_LEVELS = ["L3", "L4", "L5", "L6", "L7"]
GEO_TIERS = ["T1", "T2", "T3"]
READ_ROLES = ["CompAnalyst", "Recruiter", "HiringManager", "HRAdmin"]


@bp.route("/api/equity-snapshots", methods=["POST"])
def create():
    uid, role = get_actor()
    body = get_json_body()
    validate_fields(body, ["role_level", "geo_tier", "base_cents"], ["bonus_target_pct"])
    role_level = req_enum(body, "role_level", ROLE_LEVELS)
    geo_tier = req_enum(body, "geo_tier", GEO_TIERS)
    base = req_int(body, "base_cents", min_value=1)
    bonus_pct = req_number(body, "bonus_target_pct", required=False, min_value=0, default=0)
    require_role(role, ["CompAnalyst"])
    ts = db.now_ms()
    snap = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "role_level": role_level,
        "geo_tier": geo_tier,
        "base_cents": base,
        "bonus_target_pct": bonus_pct,
    }
    db.snapshots[snap["id"]] = snap
    return success(snap, status=201)


@bp.route("/api/equity-snapshots", methods=["GET"])
def list_all():
    uid, role = get_actor()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    rl = request.args.get("role_level")
    gt = request.args.get("geo_tier")
    items = sorted(db.snapshots.values(), key=lambda s: s["created_at"])
    if rl is not None:
        items = [s for s in items if s["role_level"] == rl]
    if gt is not None:
        items = [s for s in items if s["geo_tier"] == gt]
    page, pg = paginate(items, limit, offset)
    return success(list(page), response_type="array", pagination=pg)


@bp.route("/api/equity-snapshots/<snap_id>", methods=["GET"])
def get_one(snap_id):
    uid, role = get_actor()
    require_role(role, READ_ROLES)
    snap = db.snapshots.get(snap_id)
    if snap is None:
        raise_err(ERR_SNAPSHOT_NOT_FOUND, "Equity snapshot not found")
    return success(snap)
