"""CommodityPrice routes (PRD §3.2)."""
from flask import Blueprint

import errors
import response
import serializers
from db import db, stamp_create, touch
from helpers import (as_enum, as_int, as_string, get_json_body,
                     parse_pagination, paginate, query_arg, require_fields)
from middleware import authenticate, require_roles

bp = Blueprint("commodity_prices", __name__)

CATEGORIES = {"FERROUS", "NON_FERROUS"}
PRICE_STATUSES = {"ACTIVE", "SUPERSEDED"}

READ_ROLES = {"WeighMaster", "PayoutClerk", "ComplianceOfficer",
              "YardManager", "SettlementAccountant"}


def find_active_price(grade_code):
    """Return the single ACTIVE CommodityPrice for a grade_code, or None."""
    for r in db.commodity_prices.values():
        if r["grade_code"] == grade_code and r["status"] == "ACTIVE":
            return r
    return None


@bp.route("/yard/commodity-prices", methods=["POST"])
def create_price():
    _uid, role = authenticate()
    require_roles(role, {"YardManager"})
    body = get_json_body()
    require_fields(body, ["grade_code", "category",
                          "spot_price_cents_per_lb", "mill_price_cents_per_lb"])
    grade_code = as_string(body["grade_code"], "grade_code")
    category = as_enum(body["category"], "category", CATEGORIES)
    spot = as_int(body["spot_price_cents_per_lb"], "spot_price_cents_per_lb", minimum=0)
    mill = as_int(body["mill_price_cents_per_lb"], "mill_price_cents_per_lb", minimum=0)

    # Supersede any prior ACTIVE row for this grade_code.
    prior = find_active_price(grade_code)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)

    record = {
        "grade_code": grade_code,
        "category": category,
        "spot_price_cents_per_lb": spot,
        "mill_price_cents_per_lb": mill,
        "status": "ACTIVE",
    }
    stamp_create(record)
    db.commodity_prices[record["id"]] = record
    return response.success(serializers.commodity_price(record), 201)


@bp.route("/yard/commodity-prices/<pid>", methods=["GET"])
def get_price(pid):
    authenticate()
    record = db.commodity_prices.get(pid)
    if not record:
        raise errors.not_found("Commodity price not found.")
    return response.success(serializers.commodity_price(record), 200)


@bp.route("/yard/commodity-prices", methods=["GET"])
def list_prices():
    authenticate()
    limit, offset = parse_pagination()
    grade_code = query_arg("grade_code")
    category = query_arg("category")
    status = query_arg("status")
    if category is not None and category not in CATEGORIES:
        raise errors.invalid_request("category filter is invalid.")
    if status is not None and status not in PRICE_STATUSES:
        raise errors.invalid_request("status filter is invalid.")
    rows = list(db.commodity_prices.values())
    if grade_code is not None:
        rows = [r for r in rows if r["grade_code"] == grade_code]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return response.success_list(
        [serializers.commodity_price(r) for r in page], limit, offset, total)
