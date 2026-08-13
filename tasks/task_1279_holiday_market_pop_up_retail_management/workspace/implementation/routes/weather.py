"""WeatherEvent endpoints (PRD 3.7). A triggering event recorded while the
market is OPEN flips posture to WEATHER_ALERT with the device/programming
cascade."""
from flask import Blueprint

import db
from middleware import auth, require_roles
from response import success
from services import cascades, posture
from services.core import (
    PRECIPITATIONS,
    SOURCES,
    arg,
    arg_bool,
    as_dt,
    as_enum,
    as_int,
    base_record,
    body,
    get_child,
    get_market,
    list_response,
    required,
    serialize,
)

bp = Blueprint("weather", __name__)

MO = ("MarketOperator",)
GET_ONE = ("MarketOperator", "VendorRole", "UtilityCrew")
GET_LIST = ("MarketOperator", "UtilityCrew")


@bp.post("/markets/<marketId>/weather_events")
def create_weather_event(marketId):
    user = auth()
    require_roles(user, MO)
    market = get_market(marketId)
    data = body()
    observed_at = as_dt(required(data, "observed_at"), "observed_at")
    wind_mph = as_int(required(data, "wind_mph"), "wind_mph")
    temp_f = as_int(required(data, "temp_f"), "temp_f")
    precipitation = as_enum(required(data, "precipitation"), "precipitation", PRECIPITATIONS)
    source = as_enum(required(data, "source"), "source", SOURCES)
    triggers_alert = (
        wind_mph >= market["weather_alert_threshold_wind_mph"] or precipitation == "ICE"
    )
    was_open = posture.derive_posture(market) == "OPEN"
    rec = base_record()
    rec.update(
        {
            "market_id": marketId,
            "observed_at": observed_at,
            "wind_mph": wind_mph,
            "temp_f": temp_f,
            "precipitation": precipitation,
            "source": source,
            "triggers_alert": triggers_alert,
        }
    )
    db.STORES["weather_events"][rec["id"]] = rec
    if triggers_alert and was_open:
        cascades.fire_weather_alert(market)
    return success(serialize(rec), 201)


@bp.get("/markets/<marketId>/weather_events/<weatherEventId>")
def get_weather_event(marketId, weatherEventId):
    user = auth()
    require_roles(user, GET_ONE)
    get_market(marketId)
    return success(serialize(get_child("weather_events", weatherEventId, marketId)))


@bp.get("/markets/<marketId>/weather_events")
def list_weather_events(marketId):
    user = auth()
    require_roles(user, GET_LIST)
    get_market(marketId)
    triggers = arg_bool("triggers_alert")
    source = arg("source")
    records = []
    for ev in db.STORES["weather_events"].values():
        if ev["market_id"] != marketId:
            continue
        if triggers is not None and ev["triggers_alert"] != triggers:
            continue
        if source is not None and ev["source"] != source:
            continue
        records.append(ev)
    return list_response(records)
