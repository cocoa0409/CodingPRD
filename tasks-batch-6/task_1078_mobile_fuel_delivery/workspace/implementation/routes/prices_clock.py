from flask import Blueprint, request

import store
from store import DB
from core import (get_auth, require_role, get_body, require_fields, check_enum,
                  as_int, parse_dt, ok, ok_list, paginate, sorted_records,
                  base_record)
from serializers import ser_fuel_price

bp = Blueprint("prices_clock", __name__)


@bp.post("/fuel-prices")
def create_fuel_price():
    uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["fuel_type", "zone", "price_per_gallon_cents", "effective_date"])
    check_enum(body["fuel_type"], store.FUEL_TYPES, "fuel_type")
    check_enum(body["zone"], store.ZONES, "zone")
    as_int(body["price_per_gallon_cents"], "price_per_gallon_cents", minimum=1)
    eff = parse_dt(body["effective_date"])
    rec = base_record(with_version=False)
    rec.update({
        "fuel_type": body["fuel_type"],
        "zone": body["zone"],
        "price_per_gallon_cents": body["price_per_gallon_cents"],
        "effective_date": eff,
    })
    DB.fuel_prices[rec["id"]] = rec
    return ok(ser_fuel_price(rec), status=201)


@bp.get("/fuel-prices")
def list_fuel_prices():
    uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Member", "FleetManager"})
    items = sorted_records(DB.fuel_prices)
    ft = request.args.get("fuel_type")
    zone = request.args.get("zone")
    if ft:
        items = [p for p in items if p["fuel_type"] == ft]
    if zone:
        items = [p for p in items if p["zone"] == zone]
    page, total, limit, offset = paginate(items)
    return ok_list([ser_fuel_price(p) for p in page], total, limit, offset)


@bp.post("/_clock/set_current_utc")
def set_clock():
    uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_dt(body["to_iso8601"])
    DB.set_clock(dt)
    return ok(None)
