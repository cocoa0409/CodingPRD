"""Market endpoints: create/get/list, open_market, clear_weather_alert,
cancel, run_ops."""
from datetime import timedelta

from flask import Blueprint

import clock
import db
from errors import ApiError, invalid_state, posture_forbidden, validation
from middleware import auth, require_roles
from response import success
from services import cascades, posture
from services.core import (
    arg,
    as_bool,
    as_dict,
    as_dt,
    as_int,
    as_str,
    base_record,
    body,
    get_market,
    list_response,
    required,
    serialize_market,
    touch,
)

bp = Blueprint("markets", __name__)

ALL_ROLES = (
    "MarketOperator",
    "VendorRole",
    "JuryMember",
    "JuryChair",
    "UtilityCrew",
    "FinanceOfficer",
)
MO = ("MarketOperator",)


@bp.post("/markets")
def create_market():
    user = auth()
    require_roles(user, MO)
    data = body()
    name = as_str(required(data, "name"), "name")
    season_code = as_str(required(data, "season_code"), "season_code")
    opens_at = as_dt(required(data, "opens_at"), "opens_at")
    closes_at = as_dt(required(data, "closes_at"), "closes_at")
    app_opens = as_dt(required(data, "application_opens_at"), "application_opens_at")
    app_closes = as_dt(required(data, "application_closes_at"), "application_closes_at")
    category_caps = as_dict(required(data, "category_caps"), "category_caps")
    chalet_count = as_int(required(data, "chalet_count"), "chalet_count")
    standard_booth_count = as_int(
        required(data, "standard_booth_count"), "standard_booth_count"
    )
    jury_quorum = as_int(data.get("jury_quorum", 3), "jury_quorum")
    shared_pos_enabled = as_bool(data.get("shared_pos_enabled", True), "shared_pos_enabled")
    shared_pos_fee_bps = as_int(data.get("shared_pos_fee_bps", 250), "shared_pos_fee_bps")
    threshold = as_int(
        data.get("weather_alert_threshold_wind_mph", 35), "weather_alert_threshold_wind_mph"
    )
    if not closes_at > opens_at:
        raise validation("closes_at must be strictly after opens_at")
    rec = base_record()
    rec.update(
        {
            "name": name,
            "season_code": season_code,
            "opens_at": opens_at,
            "closes_at": closes_at,
            "application_opens_at": app_opens,
            "application_closes_at": app_closes,
            "jury_quorum": jury_quorum,
            "category_caps": category_caps,
            "chalet_count": chalet_count,
            "standard_booth_count": standard_booth_count,
            "shared_pos_enabled": shared_pos_enabled,
            "shared_pos_fee_bps": shared_pos_fee_bps,
            "weather_alert_threshold_wind_mph": threshold,
            "run_ops_index": 0,
            "_opened_flag": False,
            "_cancelled_flag": False,
            "_weather_alert_flag": False,
            "_season_close_cascaded": False,
        }
    )
    db.STORES["markets"][rec["id"]] = rec
    return success(serialize_market(rec), 201)


@bp.get("/markets")
def list_markets():
    user = auth()
    require_roles(user, ALL_ROLES)
    season_code = arg("season_code")
    posture_filter = arg("posture")
    records = []
    for m in db.STORES["markets"].values():
        if season_code is not None and m["season_code"] != season_code:
            continue
        if posture_filter is not None and posture.derive_posture(m) != posture_filter:
            continue
        records.append(m)
    return list_response(records, serialize_market)


@bp.get("/markets/<marketId>")
def get_market_endpoint(marketId):
    user = auth()
    require_roles(user, ALL_ROLES)
    return success(serialize_market(get_market(marketId)))


@bp.post("/markets/<marketId>/open_market")
def open_market(marketId):
    user = auth()
    require_roles(user, MO)
    market = get_market(marketId)
    data = body()
    expected = data.get("expected_market_version")
    if expected is not None and expected != market["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_market_version does not match the market's current version",
            412,
        )
    if posture.derive_posture(market) != "SETUP":
        raise invalid_state("market is not in SETUP posture")
    if clock.now() < market["opens_at"] - timedelta(days=7):
        raise posture_forbidden("market cannot open more than 7 days before opens_at")
    has_active = any(
        a["market_id"] == marketId and a["status"] == "ACTIVE"
        for a in db.STORES["assignments"].values()
    )
    if not has_active:
        raise posture_forbidden("at least one ACTIVE booth assignment is required to open")
    if posture.has_recent_alert(marketId):
        raise posture_forbidden("a triggering weather event occurred within the past 6 hours")
    market["_opened_flag"] = True
    touch(market)
    return success(serialize_market(market))


@bp.post("/markets/<marketId>/clear_weather_alert")
def clear_weather_alert(marketId):
    user = auth()
    require_roles(user, MO)
    market = get_market(marketId)
    if posture.derive_posture(market) != "WEATHER_ALERT":
        raise invalid_state("market is not in WEATHER_ALERT posture")
    if posture.has_recent_alert(marketId):
        raise posture_forbidden("a triggering weather event occurred within the past 6 hours")
    cascades.clear_weather_alert(market)
    return success(serialize_market(market))


@bp.post("/markets/<marketId>/cancel")
def cancel_market(marketId):
    user = auth()
    require_roles(user, MO)
    market = get_market(marketId)
    if posture.derive_posture(market) != "SETUP":
        raise invalid_state("only a market in SETUP posture can be cancelled")
    cascades.cancel_market(market)
    return success(serialize_market(market))


@bp.post("/markets/<marketId>/run_ops")
def run_ops(marketId):
    user = auth()
    require_roles(user, MO)
    market = get_market(marketId)
    cascades.run_ops(market)
    return success(serialize_market(market))
