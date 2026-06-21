"""Availability endpoints (PRD §3.2).

POST   /availabilities
GET    /availabilities
GET    /availabilities/{id}
POST   /availabilities/{id}/withdraw   ACTIVE -> WITHDRAWN
"""
from flask import Blueprint, request

import db
import lookup
import serialize
from errors import err, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import get_user_context, require_role
from pagination import get_pagination, paginate
from response import object_response, array_response
from services import validate
from timeutil import parse_iso

bp = Blueprint("availabilities", __name__)

KINDS = {"AVAILABLE", "BLACKOUT"}
READ_ROLES = {"LeagueAdmin", "Assignor", "Official", "Evaluator"}


@bp.route("/availabilities", methods=["POST"])
def create_availability():
    _, role = get_user_context()
    require_role(role, {"Official", "LeagueAdmin"})
    data = validate.body()
    official_id = validate.require_str(data, "official_id")
    start_raw = validate.require_str(data, "window_start_utc")
    end_raw = validate.require_str(data, "window_end_utc")
    kind = validate.enum(data, "kind", KINDS, required=False, default="AVAILABLE")
    with db.lock:
        lookup.official(official_id)
        try:
            ws = parse_iso(start_raw)
            we = parse_iso(end_raw)
        except ValueError:
            err(ERR_INVALID_REQUEST, "window timestamps must be ISO 8601")
        if not (we > ws):
            err(ERR_INVALID_REQUEST, "window_end_utc must be after window_start_utc")
        rec = {
            "official_id": official_id,
            "window_start_utc": start_raw,
            "window_end_utc": end_raw,
            "kind": kind,
            "status": "ACTIVE",
        }
        db.stamp_create(rec)
        db.availabilities[rec["id"]] = rec
    return object_response(serialize.availability(rec), 201)


@bp.route("/availabilities", methods=["GET"])
def list_availabilities():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    official_id = request.args.get("official_id")
    with db.lock:
        rows = list(db.availabilities.values())
        if official_id is not None:
            rows = [a for a in rows if a["official_id"] == official_id]
        page, total = paginate(rows, limit, offset)
        items = [serialize.availability(r) for r in page]
    return array_response(items, limit, offset, total)


@bp.route("/availabilities/<avail_id>", methods=["GET"])
def get_availability(avail_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    with db.lock:
        rec = lookup.availability(avail_id)
        return object_response(serialize.availability(rec))


@bp.route("/availabilities/<avail_id>/withdraw", methods=["POST"])
def withdraw_availability(avail_id):
    _, role = get_user_context()
    require_role(role, {"Official", "LeagueAdmin"})
    with db.lock:
        rec = lookup.availability(avail_id)
        if rec["status"] != "ACTIVE":
            err(ERR_INVALID_STATE, "availability not ACTIVE")
        rec["status"] = "WITHDRAWN"
        db.touch(rec)
        return object_response(serialize.availability(rec))
