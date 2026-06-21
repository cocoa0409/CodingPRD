"""YieldRule endpoints (PRD §3.3)."""
from flask import Blueprint, request

from db import db, new_id
from middleware import authenticate, require_role
from response import success, list_success
from errors import err, ERR_INVALID_REQUEST, ERR_FK_NOT_FOUND
from services.common import (
    get_body, require_str, require_number, require_int, opt_bool,
    stamp_new, parse_pagination, sort_by_created, get_or_404,
)
from services.serialize import ser_yield_rule

bp = Blueprint("yield_rules", __name__)

READ_ROLES = {"RevenueManager", "Analyst"}


@bp.route("/yield-rules", methods=["POST"])
def create_yield_rule():
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    body = get_body()
    property_id = require_str(body, "property_id")
    name = require_str(body, "name")
    occ_threshold = require_number(body, "occupancy_threshold_pct")
    if occ_threshold < 0 or occ_threshold > 1:
        raise err(ERR_INVALID_REQUEST, "occupancy_threshold_pct must be in [0, 1]")
    adjustment_pct = require_number(body, "adjustment_pct")
    priority = require_int(body, "priority")
    if priority < 1:
        raise err(ERR_INVALID_REQUEST, "priority must be >= 1")
    enabled = opt_bool(body, "enabled", True)

    if property_id not in db.properties:
        raise err(ERR_FK_NOT_FOUND, "property_id does not reference an existing property")

    rec = {
        "id": new_id(),
        "property_id": property_id,
        "name": name,
        "occupancy_threshold_pct": occ_threshold,
        "adjustment_pct": adjustment_pct,
        "priority": priority,
        "enabled": enabled,
        "_seq": db.next_seq(),
    }
    stamp_new(rec)
    db.yield_rules[rec["id"]] = rec
    return success(ser_yield_rule(rec), status=201)


@bp.route("/yield-rules/<yid>", methods=["GET"])
def get_yield_rule(yid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    rec = get_or_404(db.yield_rules, yid)
    return success(ser_yield_rule(rec), status=200)


@bp.route("/yield-rules", methods=["GET"])
def list_yield_rules():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    property_id = request.args.get("property_id")
    items = [r for r in db.yield_rules.values()
             if property_id is None or r["property_id"] == property_id]
    items = sort_by_created(items)
    total = len(items)
    page = [ser_yield_rule(r) for r in items[offset:offset + limit]]
    return list_success(page, limit, offset, total)
