"""Property endpoints (PRD §3.1, §3.8)."""
from flask import Blueprint, request

from db import db, new_id, now_iso
from middleware import authenticate, require_role
from response import success, list_success
from errors import err, ERR_INVALID_REQUEST
from services.common import (
    get_body, require_str, require_int, opt_number, opt_str,
    stamp_new, parse_pagination, sort_by_created, get_or_404,
)
from services.serialize import ser_property
from services.calc import recompute_property_kpi

bp = Blueprint("properties", __name__)

ALL_ROLES = {"RevenueManager", "GroupSalesManager", "ChannelManager", "Analyst"}


@bp.route("/properties", methods=["POST"])
def create_property():
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    body = get_body()
    name = require_str(body, "name")
    total_rooms = require_int(body, "total_rooms")
    if total_rooms < 1:
        raise err(ERR_INVALID_REQUEST, "total_rooms must be >= 1")
    overbooking = opt_number(body, "overbooking_limit_pct", 0.0)
    if overbooking < 0 or overbooking > 0.30:
        raise err(ERR_INVALID_REQUEST, "overbooking_limit_pct must be in [0, 0.30]")
    currency = opt_str(body, "currency", "USD")

    rec = {
        "id": new_id(),
        "name": name,
        "total_rooms": total_rooms,
        "overbooking_limit_pct": overbooking,
        "currency": currency,
        "occupancy_pct": 0,
        "adr": 0,
        "revpar": 0,
        "_seq": db.next_seq(),
    }
    stamp_new(rec)
    db.properties[rec["id"]] = rec
    return success(ser_property(rec), status=201)


@bp.route("/properties/<pid>", methods=["GET"])
def get_property(pid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.properties, pid)
    return success(ser_property(rec), status=200)


@bp.route("/properties", methods=["GET"])
def list_properties():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.properties.values()))
    total = len(items)
    page = [ser_property(r) for r in items[offset:offset + limit]]
    return list_success(page, limit, offset, total)


@bp.route("/properties/<pid>/kpis", methods=["GET"])
def get_kpis(pid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.properties, pid)
    recompute_property_kpi(rec)
    return success(ser_property(rec), status=200)
