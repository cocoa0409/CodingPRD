"""HedgePosition routes (PRD §3.8): open, list, manual close."""
from flask import Blueprint

import errors
import response
import serializers
from db import db, stamp_create, touch
from helpers import (as_enum, as_int, as_number, get_json_body,
                     parse_pagination, paginate, query_arg, require_fields)
from middleware import authenticate, require_roles

bp = Blueprint("hedges", __name__)

CATEGORIES = {"FERROUS", "NON_FERROUS"}
HEDGE_STATUSES = {"OPEN", "CLOSED"}
READ_ROLES = {"SettlementAccountant", "YardManager", "ComplianceOfficer"}


@bp.route("/yard/hedges", methods=["POST"])
def create_hedge():
    _uid, role = authenticate()
    require_roles(role, {"SettlementAccountant"})
    body = get_json_body()
    require_fields(body, ["category", "hedged_weight_lb", "locked_price_cents_per_lb"])
    category = as_enum(body["category"], "category", CATEGORIES)
    hedged_weight = as_number(body["hedged_weight_lb"], "hedged_weight_lb", positive=True)
    locked = as_int(body["locked_price_cents_per_lb"], "locked_price_cents_per_lb", minimum=0)

    record = {
        "category": category,
        "hedged_weight_lb": hedged_weight,
        "locked_price_cents_per_lb": locked,
        "realized_weight_lb": 0,
        "realized_pnl_cents": 0,
        "status": "OPEN",
    }
    stamp_create(record)
    db.hedges[record["id"]] = record
    return response.success(serializers.hedge(record), 201)


@bp.route("/yard/hedges/<hid>", methods=["GET"])
def get_hedge(hid):
    authenticate()
    record = db.hedges.get(hid)
    if not record:
        raise errors.not_found("Hedge position not found.")
    return response.success(serializers.hedge(record), 200)


@bp.route("/yard/hedges", methods=["GET"])
def list_hedges():
    authenticate()
    limit, offset = parse_pagination()
    category = query_arg("category")
    status = query_arg("status")
    if category is not None and category not in CATEGORIES:
        raise errors.invalid_request("category filter is invalid.")
    if status is not None and status not in HEDGE_STATUSES:
        raise errors.invalid_request("status filter is invalid.")
    rows = list(db.hedges.values())
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return response.success_list(
        [serializers.hedge(r) for r in page], limit, offset, total)


@bp.route("/yard/hedges/<hid>/close", methods=["POST"])
def close_hedge(hid):
    _uid, role = authenticate()
    require_roles(role, {"SettlementAccountant"})
    record = db.hedges.get(hid)
    if not record:
        raise errors.not_found("Hedge position not found.")
    if record["status"] != "OPEN":
        raise errors.invalid_state("Hedge is not OPEN.")
    record["status"] = "CLOSED"
    touch(record)
    return response.success(serializers.hedge(record), 200)
