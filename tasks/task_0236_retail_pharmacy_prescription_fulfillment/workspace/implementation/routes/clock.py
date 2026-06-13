"""Logical clock endpoints (PRD §2.4)."""
from flask import Blueprint

import db
from clock import parse_iso, format_iso
from common import get_body, require_field
from errors import err
from middleware import get_actor, require_roles
from response import object_response

bp = Blueprint("clock", __name__)

ALL_ROLES = ["PharmacyAdmin", "Pharmacist", "Technician", "Cashier"]


@bp.route("/_clock/set", methods=["POST"])
def set_clock():
    _uid, role = get_actor()
    require_roles(role, ["PharmacyAdmin"])
    body = get_body()
    raw = require_field(body, "current_utc")
    try:
        dt = parse_iso(raw)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "current_utc must be an ISO 8601 timestamp")
    with db.LOCK:
        clock = db.get_clock()
        clock["current_utc"] = format_iso(dt)
    return object_response(serialize(clock), 200)


@bp.route("/_clock", methods=["GET"])
def get_clock():
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    return object_response(serialize(db.get_clock()), 200)


def serialize(clock):
    return {
        "id": clock["id"],
        "created_at": clock["created_at"],
        "current_utc": clock["current_utc"],
    }
