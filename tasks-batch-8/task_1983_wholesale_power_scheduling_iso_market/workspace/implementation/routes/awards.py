from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from auth import parse_auth, require_role
from db import store
from envelope import ok, paginate
from errors import (not_found, invalid_request, conflict, ERR_INVALID_STATE,
                    ERR_MARKET_NOT_OPEN, ERR_AWARD_OVERLAPS_OUTAGE)
from routes.operating_days import get_day
from routes.generators import get_generator
from util import (get_body, check_unknown, req_string, req_int, req_enum,
                  req_number, opt_int, opt_number, new_record, serialize,
                  sort_key, touch, parse_date)

bp = Blueprint("awards", __name__)

SERVICE_TYPES = ("REGULATION", "SYNC_RESERVE", "SUPPLEMENTAL_RESERVE")


def get_award(aid):
    a = store.awards.get(aid)
    if a is None:
        raise not_found("ancillary service award not found")
    return a


def _award_overlaps_outage(gen_id, day, start_interval, end_interval):
    """Interval-granularity intersection with APPROVED outage windows."""
    day_start = parse_date(day["market_date"])
    for o in store.outages.values():
        if o["generator_asset_id"] != gen_id or o["status"] != "APPROVED":
            continue
        for i in range(start_interval, end_interval + 1):
            iv_start = day_start + timedelta(hours=i - 1)
            iv_end = day_start + timedelta(hours=i)
            if o["_start_dt"] < iv_end and iv_start < o["_end_dt"]:
                return True
    return False


@bp.post("/market/operating-days/<operatingDayId>/awards")
def create_award(operatingDayId):
    auth = parse_auth()
    require_role(auth, ["IsoOperator"])
    body = get_body()
    check_unknown(body, {"generator_asset_id", "service_type", "awarded_mw",
                         "capacity_price_cents", "performance_price_cents",
                         "mileage_ratio", "start_interval", "end_interval"})
    gen_id = req_string(body, "generator_asset_id")
    service_type = req_enum(body, "service_type", SERVICE_TYPES)
    awarded_mw = req_number(body, "awarded_mw", minimum=Decimal(0), min_exclusive=True)
    capacity_price = req_int(body, "capacity_price_cents")
    performance_price = opt_int(body, "performance_price_cents")
    mileage_ratio = opt_number(body, "mileage_ratio")
    start_interval = req_int(body, "start_interval", minimum=1, maximum=24)
    end_interval = req_int(body, "end_interval", minimum=1, maximum=24)
    if end_interval < start_interval:
        raise invalid_request("end_interval must be >= start_interval")
    if service_type == "REGULATION":
        if performance_price is None or mileage_ratio is None:
            raise invalid_request(
                "REGULATION awards require performance_price_cents and mileage_ratio")

    day = get_day(operatingDayId)
    gen = get_generator(gen_id)
    if day["status"] not in ("DA_OPEN", "DA_GATED"):
        raise conflict(ERR_MARKET_NOT_OPEN,
                       "awards are accepted only while DA_OPEN or DA_GATED")
    if _award_overlaps_outage(gen["id"], day, start_interval, end_interval):
        raise conflict(ERR_AWARD_OVERLAPS_OUTAGE,
                       "award window intersects an APPROVED outage window")

    rec = new_record()
    rec.update({
        "generator_asset_id": gen["id"],
        "operating_day_id": day["id"],
        "service_type": service_type,
        "awarded_mw": awarded_mw,
        "capacity_price_cents": capacity_price,
        "performance_price_cents": performance_price,
        "mileage_ratio": mileage_ratio,
        "start_interval": start_interval,
        "end_interval": end_interval,
        "performance_score": None,
        "revenue_cents": 0,
        "status": "AWARDED",
    })
    store.awards[rec["id"]] = rec
    return ok(serialize(rec), status=201)


@bp.get("/market/awards/<awardId>")
def get_one(awardId):
    parse_auth()
    return ok(serialize(get_award(awardId)))


@bp.get("/market/awards")
def list_awards():
    parse_auth()
    rows = sorted(store.awards.values(), key=sort_key)
    gen_id = request.args.get("generator_asset_id")
    day_id = request.args.get("operating_day_id")
    status = request.args.get("status")
    if gen_id is not None:
        rows = [r for r in rows if r["generator_asset_id"] == gen_id]
    if day_id is not None:
        rows = [r for r in rows if r["operating_day_id"] == day_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate([serialize(r) for r in rows])


@bp.post("/market/awards/<awardId>/cancel")
def cancel_award(awardId):
    auth = parse_auth()
    require_role(auth, ["IsoOperator"])
    award = get_award(awardId)
    if award["status"] != "AWARDED":
        raise conflict(ERR_INVALID_STATE, "only an AWARDED award can be cancelled")
    day = store.operating_days[award["operating_day_id"]]
    if day["status"] not in ("DA_OPEN", "DA_GATED", "RT_COMPLETE"):
        raise conflict(ERR_INVALID_STATE,
                       "awards cannot be cancelled once preliminary settlement has run")
    award["status"] = "CANCELLED"  # revenue stays 0; excluded from settlement
    touch(award)
    return ok(serialize(award))
