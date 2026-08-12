"""Aircraft endpoints."""

from flask import Blueprint

from db import aircraft_store, trust_agreement_store, make_common_fields, touch
from errors import ApiError, ERR_NOT_FOUND, ERR_DUPLICATE_N_NUMBER
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from validators import (
    get_body, require_fields, require_string, require_positive_int,
    require_non_negative_int,
)

bp = Blueprint("aircraft", __name__)


@bp.route("/api/aircraft", methods=["POST"])
def create_aircraft():
    user_id, role = require_roles(["EscrowOfficer"])
    body = get_body()
    require_fields(body, ["n_number", "serial_number", "make_model", "year"], ["is_international_registry"])

    n_number = require_string(body["n_number"], "n_number")
    serial_number = require_string(body["serial_number"], "serial_number")
    make_model = require_string(body["make_model"], "make_model")
    year = body["year"]
    if not isinstance(year, int) or isinstance(year, bool) or not (1900 <= year <= 2100):
        raise ApiError("ERR_INVALID_REQUEST", "year must be an integer between 1900 and 2100.", 400)
    is_ir = body.get("is_international_registry", False)
    if not isinstance(is_ir, bool):
        raise ApiError("ERR_INVALID_REQUEST", "is_international_registry must be a boolean.", 400)

    # Unique n_number check
    for ac in aircraft_store.values():
        if ac["n_number"] == n_number:
            raise ApiError(ERR_DUPLICATE_N_NUMBER, f"Aircraft with n_number {n_number} already exists.", 409)

    fields = make_common_fields()
    aircraft = {
        **fields,
        "n_number": n_number,
        "serial_number": serial_number,
        "make_model": make_model,
        "year": year,
        "is_international_registry": is_ir,
        "registry_status": "REGISTERED",
    }
    aircraft_store[aircraft["id"]] = aircraft
    return success_object(aircraft, 201)


@bp.route("/api/aircraft/<id>", methods=["GET"])
def get_aircraft(id):
    user_id, role = require_roles(ALL_ROLES)
    ac = aircraft_store.get(id)
    if not ac:
        raise ApiError(ERR_NOT_FOUND, "Aircraft not found.", 404)
    return success_object(ac)


@bp.route("/api/aircraft/<id>/trust-agreements", methods=["GET"])
def list_aircraft_trust_agreements(id):
    user_id, role = require_roles(ALL_ROLES)
    ac = aircraft_store.get(id)
    if not ac:
        raise ApiError(ERR_NOT_FOUND, "Aircraft not found.", 404)

    items = [ta for ta in trust_agreement_store.values() if ta["aircraft_id"] == id]
    items.sort(key=lambda x: x["created_at"])

    limit = _parse_limit()
    offset = _parse_offset()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list(items, limit, offset, total)


def _parse_limit():
    from flask import request
    try:
        v = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        v = 10
    return max(1, min(100, v))


def _parse_offset():
    from flask import request
    try:
        v = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        v = 0
    return max(0, v)
