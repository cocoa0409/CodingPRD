"""GLAccount endpoints (PRD §3.1).

Lightweight record: id + created_at only (no updated_at/version).
"""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import auth_required
from response import ok_object
from routes._helpers import get_body, require_fields, serialize, is_str, is_bool
from services.common import new_lightweight_fields

bp = Blueprint("gl_accounts", __name__)


@bp.post("/ap/gl-accounts")
def create_gl_account():
    auth_required({"APManager"})()
    body = get_body()
    require_fields(body, ["code", "name"])

    code = body["code"]
    if not is_str(code) or not code:
        raise APIError(ERR_INVALID_REQUEST, 400, "code must be a non-empty string")
    if not is_str(body["name"]) or not body["name"]:
        raise APIError(ERR_INVALID_REQUEST, 400, "name must be a non-empty string")

    is_postable = body.get("is_postable", True)
    if not is_bool(is_postable):
        raise APIError(ERR_INVALID_REQUEST, 400, "is_postable must be a boolean")

    # code must be unique across all GL accounts (PRD §3.1).
    for g in db.gl_accounts.values():
        if g["code"] == code:
            raise APIError(ERR_INVALID_REQUEST, 400, "GL account code must be unique")

    gl = {
        **new_lightweight_fields(),
        "code": code,
        "name": body["name"],
        "is_postable": is_postable,
    }
    db.gl_accounts[gl["id"]] = gl
    return ok_object(serialize(gl), http_status=201)


def find_gl_by_code(code: str):
    for g in db.gl_accounts.values():
        if g["code"] == code:
            return g
    return None
