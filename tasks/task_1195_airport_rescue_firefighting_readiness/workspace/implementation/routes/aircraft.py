"""Aircraft register."""
from flask import Blueprint, request

from db import store, base_entity, touch, serialize
from errors import ApiError, ERR_AIRCRAFT_NOT_FOUND, ERR_VALIDATION_FAILED
from middleware import (
    require, json_body, need_str, need_number, opt_str, opt_number, opt_bool,
    ALL_ROLES,
)
from response import success, paginated
from services import calc

bp = Blueprint("aircraft", __name__)


def get_aircraft_or_404(aid):
    a = store.aircraft.get(aid)
    if a is None:
        raise ApiError(ERR_AIRCRAFT_NOT_FOUND, 404, "Aircraft id does not exist")
    return a


@bp.post("/arff/aircraft")
def create_aircraft():
    require(["AirportManager"])
    data = json_body()
    model = need_str(data, "model_name", nonempty=True)
    length = need_number(data, "length_ft", min_value=0, exclusive_min=True)
    deps = need_number(data, "avg_daily_departures", min_value=0)
    inservice = data.get("in_scheduled_service", True)
    if not isinstance(inservice, bool):
        raise ApiError(ERR_VALIDATION_FAILED, 400,
                       "'in_scheduled_service' must be a boolean")
    a = base_entity()
    a.update({
        "model_name": model,
        "length_ft": length,
        "avg_daily_departures": deps,
        "in_scheduled_service": inservice,
    })
    calc.refresh_aircraft(a)
    store.aircraft[a["id"]] = a
    calc.recompute_profile(bump="always")
    return success(serialize(a), "object", 201)


@bp.get("/arff/aircraft")
def list_aircraft():
    require(ALL_ROLES)
    items = list(store.aircraft.values())
    raw = request.args.get("in_scheduled_service")
    if raw is not None:
        low = raw.lower()
        if low not in ("true", "false"):
            raise ApiError(ERR_VALIDATION_FAILED, 400,
                           "'in_scheduled_service' filter must be true or false")
        want = low == "true"
        items = [a for a in items if a["in_scheduled_service"] == want]
    return paginated(items)


@bp.get("/arff/aircraft/<aid>")
def get_aircraft(aid):
    require(ALL_ROLES)
    return success(serialize(get_aircraft_or_404(aid)), "object", 200)


@bp.patch("/arff/aircraft/<aid>")
def update_aircraft(aid):
    require(["AirportManager"])
    a = get_aircraft_or_404(aid)
    data = json_body()
    a["model_name"] = opt_str(data, "model_name", a["model_name"], nonempty=True)
    a["length_ft"] = opt_number(data, "length_ft", a["length_ft"],
                                min_value=0, exclusive_min=True)
    a["avg_daily_departures"] = opt_number(data, "avg_daily_departures",
                                           a["avg_daily_departures"], min_value=0)
    a["in_scheduled_service"] = opt_bool(data, "in_scheduled_service",
                                         a["in_scheduled_service"])
    calc.refresh_aircraft(a)
    touch(a)
    calc.recompute_profile(bump="always")
    return success(serialize(a), "object", 200)


@bp.get("/arff/aircraft/<aid>/index-determinations")
def list_aircraft_determinations(aid):
    require(ALL_ROLES)
    get_aircraft_or_404(aid)
    items = [d for d in store.determinations.values() if d["largest_aircraft_id"] == aid]
    return paginated(items)


@bp.get("/arff/aircraft/<aid>/incidents")
def list_aircraft_incidents(aid):
    require(ALL_ROLES)
    get_aircraft_or_404(aid)
    items = [i for i in store.incidents.values() if i["aircraft_id"] == aid]
    return paginated(items)
