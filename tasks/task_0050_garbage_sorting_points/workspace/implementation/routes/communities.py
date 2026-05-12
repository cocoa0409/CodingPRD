"""Community endpoints."""

from __future__ import annotations

from flask import Blueprint, jsonify

from db import db
from errors import ERR_VALIDATION, raise_api_error
from middleware import require_roles
from response import success_response
from services.common import (
    CMTY_CODE_RE,
    get_json_body,
    optional_str,
    require_str,
)
from services.lookup import get_community

bp = Blueprint("communities", __name__)


@bp.post("/communities")
@require_roles("SystemOperator")
def create_community():
    body = get_json_body()
    name = require_str(body, "name", min_len=1, max_len=80)
    code = require_str(body, "code", min_len=1, max_len=64)
    if not CMTY_CODE_RE.match(code):
        raise_api_error(ERR_VALIDATION, "code must match ^CMTY-[0-9]{3,6}$")
    timezone = body.get("timezone", "UTC")
    if timezone is None:
        timezone = "UTC"
    if not isinstance(timezone, str) or not timezone:
        raise_api_error(ERR_VALIDATION, "timezone must be a non-empty string.")

    # Uniqueness checks
    for c in db.communities.values():
        if c["name"] == name:
            raise_api_error(ERR_VALIDATION, "Community name must be unique.")
        if c["code"] == code:
            raise_api_error(ERR_VALIDATION, "Community code must be unique.")

    obj = {
        "name": name,
        "code": code,
        "timezone": timezone,
        "status": "ACTIVE",
        "community_id": None,  # not applicable; remove after stamp
    }
    obj.pop("community_id", None)
    db.stamp_create(obj)
    db.communities[obj["id"]] = obj
    return jsonify(success_response(obj)), 201


@bp.get("/communities/<community_id>")
@require_roles("SystemOperator", "CommunityAdmin", "AppealReviewer")
def read_community(community_id: str):
    c = get_community(community_id)
    return jsonify(success_response(c)), 200
