"""Production endpoints."""

from flask import Blueprint, request
from middleware import require_role, ALL_ROLES
from response import success_object, success_list
from errors import *
from db import store
from services.helpers import (
    require_fields, require_int, require_str,
    make_entity, touch, get_production, list_filtered, paginate, get_pagination_params,
)

bp = Blueprint("productions", __name__)


@bp.route("/productions", methods=["POST"])
def create_production():
    user_id, role = require_role("LocationManager")
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["title", "production_company", "cast_size", "umbrella_liability_limit_cents"])
    entity = make_entity({
        "title": require_str(payload, "title"),
        "production_company": require_str(payload, "production_company"),
        "cast_size": require_int(payload, "cast_size"),
        "umbrella_liability_limit_cents": require_int(payload, "umbrella_liability_limit_cents"),
        "status": "PREP",
    })
    store.productions[entity["id"]] = entity
    return success_object(entity, 201)


@bp.route("/productions/<pid>", methods=["GET"])
def get_production_by_id(pid):
    user_id, role = require_role(*ALL_ROLES)
    p = get_production(pid)
    return success_object(p)


@bp.route("/productions/<pid>/wrap", methods=["POST"])
def wrap_production(pid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    if p["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Production must be ACTIVE to wrap", 409)
    # Gate 1: all permit applications terminal (not in DRAFT, SUBMITTED, UNDER_REVIEW, CONDITIONALLY_APPROVED)
    for pa in store.permit_applications.values():
        if pa.get("production_id") == pid and pa["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "CONDITIONALLY_APPROVED"):
            raise ApiError(ERR_APPLICATIONS_OPEN, "Open permit applications exist", 409)
    # Gate 2: all deposit accounts CLOSED
    for da in store.deposit_accounts.values():
        if da.get("production_id") == pid and da["status"] != "CLOSED":
            raise ApiError(ERR_DEPOSITS_OPEN, "Open deposit accounts exist", 409)
    # Gate 3: no OPEN or ACKNOWLEDGED complaints
    for c in store.complaints.values():
        if c.get("production_id") == pid and c["status"] in ("OPEN", "ACKNOWLEDGED"):
            raise ApiError(ERR_COMPLAINTS_OPEN, "Open complaints exist", 409)
    p["status"] = "WRAPPED"
    touch(p)
    return success_object(p)


@bp.route("/productions/<pid>/cancel", methods=["POST"])
def cancel_production(pid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    if p["status"] != "PREP":
        raise ApiError(ERR_INVALID_STATE, "Production must be PREP to cancel", 409)
    # No ShootDay has reached READY or beyond
    for sd in store.shoot_days.values():
        if sd.get("production_id") == pid and sd["status"] in ("READY", "IN_PROGRESS", "COMPLETED", "SHUT_DOWN"):
            raise ApiError(ERR_INVALID_STATE, "A shoot day has already reached READY or beyond", 409)
    p["status"] = "CANCELLED"
    touch(p)
    # Withdraw all DRAFT/SUBMITTED permit applications
    for pa in store.permit_applications.values():
        if pa.get("production_id") == pid and pa["status"] in ("DRAFT", "SUBMITTED"):
            pa["status"] = "WITHDRAWN"
            touch(pa)
    # Collapse all PROPOSED/COUNTERED owner agreements
    for oa in store.owner_agreements.values():
        if oa.get("production_id") == pid and oa["status"] in ("PROPOSED", "COUNTERED"):
            oa["status"] = "COLLAPSED"
            touch(oa)
    return success_object(p)
