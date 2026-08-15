"""ScoutPackage endpoints."""

from flask import Blueprint, request
from middleware import require_role, ALL_ROLES
from response import success_object, success_list
from errors import *
from db import store
from services.helpers import (
    require_fields, require_str, require_int, require_enum,
    make_entity, touch, get_production, get_location, get_scoped,
    list_filtered, paginate, get_pagination_params,
)

bp = Blueprint("scout_packages", __name__)


@bp.route("/productions/<pid>/scout-packages", methods=["POST"])
def create_scout_package(pid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["location_id", "photo_count", "coverage_score_pct", "scout_date"])
    loc_id = require_str(payload, "location_id")
    get_location(loc_id)
    coverage_score_pct = require_int(payload, "coverage_score_pct")
    # PRD §3.2: coverage_score_pct is "between 0 and 100 inclusive".
    if coverage_score_pct < 0 or coverage_score_pct > 100:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "coverage_score_pct must be between 0 and 100 inclusive",
            400,
        )
    entity = make_entity({
        "production_id": pid,
        "location_id": loc_id,
        "photo_count": require_int(payload, "photo_count"),
        "coverage_score_pct": coverage_score_pct,
        "scout_date": require_str(payload, "scout_date"),
        "status": "DRAFT",
    })
    store.scout_packages[entity["id"]] = entity
    return success_object(entity, 201)


@bp.route("/productions/<pid>/scout-packages", methods=["GET"])
def list_scout_packages(pid):
    user_id, role = require_role(*ALL_ROLES)
    p = get_production(pid)
    limit, offset = get_pagination_params(request.args)
    filters = {}
    for f in ("location_id", "status"):
        v = request.args.get(f)
        if v:
            filters[f] = v
    items = list_filtered(store.scout_packages, filters, production_id=pid)
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/productions/<pid>/scout-packages/<rid>", methods=["GET"])
def get_scout_package(pid, rid):
    user_id, role = require_role(*ALL_ROLES)
    p = get_production(pid)
    sp = get_scoped(store.scout_packages, rid, pid, "ScoutPackage")
    return success_object(sp)


@bp.route("/productions/<pid>/scout-packages/<rid>/submit", methods=["POST"])
def submit_scout_package(pid, rid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    sp = get_scoped(store.scout_packages, rid, pid, "ScoutPackage")
    if sp["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "ScoutPackage is not DRAFT", 409)
    if sp["photo_count"] < 6:
        raise ApiError(ERR_PACKAGE_INCOMPLETE, "photo_count must be >= 6 for submission", 422)
    if p["status"] != "PREP":
        raise ApiError(ERR_INVALID_STATE, "Production must be PREP to submit scout package", 409)
    sp["status"] = "SUBMITTED"
    touch(sp)
    return success_object(sp)


@bp.route("/productions/<pid>/scout-packages/<rid>/review", methods=["POST"])
def review_scout_package(pid, rid):
    user_id, role = require_role("FilmOffice")
    p = get_production(pid)
    sp = get_scoped(store.scout_packages, rid, pid, "ScoutPackage")
    if sp["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "ScoutPackage is not SUBMITTED", 409)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["decision"])
    decision = require_enum(payload, "decision", ["ACCEPT", "REJECT"])
    sp["status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    touch(sp)
    return success_object(sp)
