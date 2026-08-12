from flask import Blueprint, request

from db import store, now, next_seq, new_id, touch, Rec
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import get_body, authenticate, paginate, sort_items
from response import ok, ok_list
from serializers import ser_advisory
from util import req_str, req_num, req_int, parse_ymd, fmt_dt3, dec
from decimal import Decimal

bp = Blueprint("weather", __name__)

READ_ROLES = ["Customer", "Agronomist", "FulfillmentOps", "PlatformAdmin"]


@bp.route("/api/weather-advisories", methods=["POST"])
def upsert_advisory():
    body = get_body()
    region = req_str(body, "region")
    date_str = parse_ymd(body.get("date"), "date").isoformat()
    rain_probability = req_num(body, "rain_probability")
    if dec(rain_probability) < Decimal("0") or dec(rain_probability) > Decimal("1"):
        raise_err(ERR_INVALID_REQUEST, "Field 'rain_probability' must be within 0..1")
    wind_kph = req_int(body, "wind_kph")
    temp_high_c = req_int(body, "temp_high_c")

    authenticate(["PlatformAdmin"])

    existing = None
    for a in store.weather_advisories.values():
        if a.region == region and a.date == date_str:
            existing = a
            break
    if existing is not None:
        # upsert: replace the previous advisory for (region, date)
        existing.rain_probability = rain_probability
        existing.wind_kph = wind_kph
        existing.temp_high_c = temp_high_c
        touch(existing)
        return ok(ser_advisory(existing), 201)

    ts = now()
    rec = Rec(
        id=new_id(), created_at=ts, updated_at=ts, version=1, seq=next_seq(),
        region=region, date=date_str, rain_probability=rain_probability,
        wind_kph=wind_kph, temp_high_c=temp_high_c,
    )
    rec.raw["created_at"] = fmt_dt3(ts)
    rec.raw["updated_at"] = fmt_dt3(ts)
    store.weather_advisories[rec.id] = rec
    return ok(ser_advisory(rec), 201)


@bp.route("/api/weather-advisories", methods=["GET"])
def list_advisories():
    authenticate(READ_ROLES)
    items = list(store.weather_advisories.values())
    region = request.args.get("region")
    if region is not None:
        items = [a for a in items if a.region == region]
    date_f = request.args.get("date")
    if date_f is not None:
        items = [a for a in items if a.date == date_f]
    items = sort_items(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_advisory(a) for a in page], total, limit, offset)
