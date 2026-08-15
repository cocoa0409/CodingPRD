"""MarketPrice endpoints (PRD §3.5) and the logical-clock endpoint (§2.10).

MarketPrice rows are immutable price publications: they carry only id and
created_at (no updated_at, no version).
"""

from datetime import datetime

from flask import Blueprint, request

import db
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import get_body, req_date, req_enum, req_int, req_str, require_roles
from response import success_list, success_object

bp = Blueprint("prices_clock", __name__)

MARKET_ZONES = {"NORTH", "SOUTH", "COASTAL"}
TANK_KINDS = {"USED_OIL", "ANTIFREEZE", "MIXED"}
READ_ROLES = ("RoutePlanner", "SettlementClerk", "Regulator", "Driver")


@bp.post("/market-prices")
@require_roles("Regulator")
def create_market_price():
    body = get_body()
    market_zone = req_enum(body, "market_zone", MARKET_ZONES)
    tank_kind = req_enum(body, "tank_kind", TANK_KINDS)
    effective_date = req_date(body, "effective_date")
    price = req_int(body, "price_cents_per_gal")
    row = db.create_entity("market_prices", {
        "market_zone": market_zone,
        "tank_kind": tank_kind,
        "effective_date": effective_date,
        "price_cents_per_gal": price,
    }, common=False)
    return success_object(db.serialize(row), 201)


@bp.get("/market-prices")
@require_roles(*READ_ROLES)
def list_market_prices():
    items = db.all_entities("market_prices")
    for param in ("market_zone", "tank_kind", "effective_date"):
        value = request.args.get(param)
        if value is not None:
            items = [m for m in items if m[param] == value]
    return success_list([db.serialize(m) for m in db.sorted_created(items)])


@bp.get("/market-prices/<marketPriceId>")
@require_roles(*READ_ROLES)
def get_market_price(marketPriceId):
    row = db.get("market_prices", marketPriceId)
    if row is None:
        raise ApiError(ERR_INVALID_REQUEST, "MarketPrice id not found", 404)
    return success_object(db.serialize(row))


def _parse_iso8601(value):
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


@bp.post("/_clock/set_current_utc")
@require_roles("RoutePlanner")
def set_current_utc():
    body = get_body()
    to_iso8601 = req_str(body, "to_iso8601")
    dt = _parse_iso8601(to_iso8601)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 datetime", 400)
    current = db.set_clock(dt)
    return success_object({"current_utc": db.fmt_ts(current)})
