"""Security endpoints: create, get, and per-security price listing."""
from flask import Blueprint

import db
from db import store
from middleware import ALL_ROLES, get_context, require_roles
from response import created, filter_arg, ok, paginate
from validation import parse_body, require_path_entity

bp = Blueprint("securities", __name__)

SECURITY_SCHEMA = {
    "security_identifier": ("string", True, None),
    "description": ("string", True, None),
    "asset_class": ("enum", True, ["EQUITY", "FIXED_INCOME", "CASH_EQUIVALENT", "DERIVATIVE"]),
    "default_pricing_level": ("enum", True, ["LEVEL_1", "LEVEL_2", "LEVEL_3"]),
    "currency": ("enum", True, ["USD", "EUR", "GBP"]),
}


@bp.post("/securities")
def create_security():
    get_context()
    require_roles(["FundAccountant"])
    body = parse_body(SECURITY_SCHEMA)
    security = {
        "id": db.new_id(),
        "security_identifier": body["security_identifier"],
        "description": body["description"],
        "asset_class": body["asset_class"],
        "default_pricing_level": body["default_pricing_level"],
        "currency": body["currency"],
    }
    db.new_common(security)
    store.securities[security["id"]] = security
    return created(security)


@bp.get("/securities/<security_id>")
def get_security(security_id):
    get_context()
    security = require_path_entity(store.securities, security_id)
    require_roles(ALL_ROLES)
    return ok(security)


@bp.get("/securities/<security_id>/prices")
def list_security_prices(security_id):
    get_context()
    security = require_path_entity(store.securities, security_id)
    require_roles(ALL_ROLES)
    rows = [o for o in store.price_observations.values()
            if o["security_id"] == security["id"]]
    rows = filter_arg(rows, "price_date")
    rows = filter_arg(rows, "status")
    page, meta = paginate(rows)
    return ok(page, rtype="array", pagination=meta)
