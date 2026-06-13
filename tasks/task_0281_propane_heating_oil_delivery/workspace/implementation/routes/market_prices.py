"""MarketPrice endpoints (PRD §2.11)."""
from flask import Blueprint, request

import db
from common import (parse_pagination, paginate, sort_by_created,
                    require_int, require_string, require_enum)
from middleware import require_auth, require_role, get_json_body
from response import object_response, array_response
from services import lookups as L

bp = Blueprint("market_prices", __name__)

FUEL_TYPES = {"PROPANE", "HEATING_OIL"}


@bp.post("/market-prices")
def create_market_price():
    _, role = require_auth()
    require_role(role, {"AccountManager"})
    body = get_json_body()
    region_code = require_string(body, "region_code")
    fuel_type = require_enum(body, "fuel_type", FUEL_TYPES)
    price = require_int(body, "market_price_cents_per_gallon", minimum=1)

    # Cascade: expire prior ACTIVE quote for same region+fuel.
    for other in db.market_prices.values():
        if (other["region_code"] == region_code
                and other["fuel_type"] == fuel_type
                and other["status"] == "ACTIVE"):
            other["status"] = "EXPIRED"
            db.touch(other)

    rec = {
        "region_code": region_code,
        "fuel_type": fuel_type,
        "market_price_cents_per_gallon": price,
        "status": "ACTIVE",
    }
    db.stamp_create_full(rec)
    db.market_prices[rec["id"]] = rec
    return object_response(L.serialize_market_price(rec), 201)


@bp.get("/market-prices/<market_price_id>")
def get_market_price(market_price_id):
    _, role = require_auth()
    require_role(role, {"AccountManager", "Dispatcher", "Customer"})
    rec = L.get_market_price(market_price_id)
    return object_response(L.serialize_market_price(rec), 200)


@bp.get("/market-prices")
def list_market_prices():
    _, role = require_auth()
    require_role(role, {"AccountManager", "Dispatcher", "Customer"})
    limit, offset = parse_pagination()
    region_code = request.args.get("region_code")
    fuel_type = request.args.get("fuel_type")
    status = request.args.get("status")

    items = list(db.market_prices.values())
    if region_code is not None:
        items = [m for m in items if m.get("region_code") == region_code]
    if fuel_type is not None:
        items = [m for m in items if m.get("fuel_type") == fuel_type]
    if status is not None:
        items = [m for m in items if m.get("status") == status]

    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([L.serialize_market_price(m) for m in page], limit, offset, total)
