"""Furnisher routes."""
from __future__ import annotations

from flask import Blueprint

from ..auth import enforce_furnisher_ownership, require_auth
from ..errors import ApiError
from ..responses import json_object
from ..store import stamp_create, store
from ..utils import parse_json_body, require_field


bp_furnishers = Blueprint("furnishers", __name__)


@bp_furnishers.route("/furnishers", methods=["POST"])
@require_auth(["PlatformAdmin"])
def create_furnisher():
    body = parse_json_body()
    legal_name = require_field(body, "legal_name", types=[str])
    ecoa_code = require_field(body, "ecoa_code", types=[str])
    if not legal_name.strip():
        raise ApiError("ERR_INVALID_REQUEST", "legal_name must be non-empty.", 400)
    if not ecoa_code.strip():
        raise ApiError("ERR_INVALID_REQUEST", "ecoa_code must be non-empty.", 400)
    with store.lock:
        furnisher = stamp_create(
            {"legal_name": legal_name, "ecoa_code": ecoa_code, "status": "ACTIVE"}
        )
        store.furnishers[furnisher["id"]] = furnisher
    return json_object(furnisher, 201)


@bp_furnishers.route("/furnishers/<furnisher_id>", methods=["GET"])
@require_auth(["PlatformAdmin", "BureauOperator", "Furnisher"])
def get_furnisher(furnisher_id: str):
    furnisher = store.furnishers.get(furnisher_id)
    if furnisher is None:
        raise ApiError("ERR_NOT_FOUND", "Furnisher not found.", 404)
    enforce_furnisher_ownership(furnisher_id)
    return json_object(furnisher, 200)
