"""Household endpoints."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from db import db
from errors import ERR_FORBIDDEN, raise_api_error
from middleware import require_roles
from response import list_response, success_response
from services.common import (
    get_json_body,
    paginate,
    parse_iso8601_utc,
    parse_pagination,
    require_str,
)
from services.lookup import get_community, get_household, get_resident_by_id

bp = Blueprint("households", __name__)


@bp.post("/communities/<community_id>/households")
@require_roles("CommunityAdmin")
def create_household(community_id: str):
    get_community(community_id)
    body = get_json_body()
    address = require_str(body, "address", min_len=1, max_len=200)
    building_code = require_str(body, "building_code", min_len=1, max_len=32)

    obj = {
        "community_id": community_id,
        "address": address,
        "building_code": building_code,
        "head_resident_id": None,
        "points_balance": 0,
        "lifetime_points_earned": 0,
        "status": "ACTIVE",
    }
    db.stamp_create(obj)
    db.households[obj["id"]] = obj
    return jsonify(success_response(obj)), 201


@bp.get("/communities/<community_id>/households/<household_id>")
@require_roles("CommunityAdmin", "AppealReviewer", "Resident")
def read_household(community_id: str, household_id: str):
    h = get_household(community_id, household_id)
    if g.user_role == "Resident":
        r = get_resident_by_id(g.user_id)
        if r is None or r.get("household_id") != household_id:
            raise_api_error(ERR_FORBIDDEN, "Resident does not own this household.")
    return jsonify(success_response(h)), 200


@bp.get("/communities/<community_id>/households")
@require_roles("CommunityAdmin")
def list_households(community_id: str):
    get_community(community_id)
    limit, offset = parse_pagination()
    building_code = request.args.get("building_code")
    status = request.args.get("status")
    items = [
        h
        for h in db.households.values()
        if h["community_id"] == community_id
        and (building_code is None or h["building_code"] == building_code)
        and (status is None or h["status"] == status)
    ]
    items.sort(key=lambda x: x["created_at"])
    page, total = paginate(items, limit, offset)
    return jsonify(list_response(page, limit, offset, total)), 200
