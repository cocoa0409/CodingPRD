"""Weather observations: record (triggers the wind shutdown sweep), read, list.
Append-only: observations carry only id and created_at."""
from flask import Blueprint

import db
from db import serialize
from errors import raise_err, ERR_INVALID_DAY_POSTURE
from helpers import get_or_404, paginate, qparam, fair_id_of_observation
from middleware import authenticate, scope_to_fair
from response import ok
from services.cascades import wind_sweep
from validators import get_body, reject_unknown, req_str, req_int, opt_str

bp = Blueprint("weather", __name__)

ALL = ["StateProgramAdmin", "StateInspector", "FairManager", "RideOperator", "TicketClerk", "CrewMember"]


@bp.post("/weather-observations")
def create_observation():
    ctx = authenticate(["FairManager", "RideOperator"])
    body = get_body()
    reject_unknown(body, {"operating_day_id", "wind_speed_mph", "note"})
    day_id = req_str(body, "operating_day_id")
    wind = req_int(body, "wind_speed_mph", lo=0, hi=200)
    note = opt_str(body, "note")
    day = db.get("operating_days", day_id)
    scope_to_fair(ctx, day["fair_id"] if day else None)
    day = get_or_404("operating_days", day_id)
    scope_to_fair(ctx, day["fair_id"])
    if day["posture"] not in ("CHECKLIST_PHASE", "OPEN", "WEATHER_HOLD"):
        raise_err(ERR_INVALID_DAY_POSTURE, "Observations are accepted only in CHECKLIST_PHASE, OPEN, or WEATHER_HOLD")
    observation = db.register(
        "observations",
        {
            "operating_day_id": day_id,
            "wind_speed_mph": wind,
            "note": note,
        },
    )
    wind_sweep(day, wind)
    return ok(serialize(observation), 201)


@bp.get("/weather-observations/<oid>")
def get_observation(oid):
    ctx = authenticate(ALL)
    observation = get_or_404("observations", oid)
    scope_to_fair(ctx, fair_id_of_observation(observation))
    return ok(serialize(observation))


@bp.get("/weather-observations")
def list_observations():
    authenticate(ALL)
    return paginate("observations", {"operating_day_id": qparam("operating_day_id")})
