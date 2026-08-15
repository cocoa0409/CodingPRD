from flask import Blueprint, request

import db
from db import new_entity, touch
from errors import ApiError, ERR_INVALID_STATE
from middleware import endpoint
from response import ok
from serializers import ser_result_flag
from services import recompute as engine
from validators import get_body, get_or_404, list_page, v_enum, v_str

bp = Blueprint("result_flags", __name__)

_READERS = ("RaceDirector", "RaceOfficial", "TimingOperator")
_FLAG_STATES = ("IN_PROGRESS", "PROVISIONAL_PUBLISHED", "AMENDMENT_OPEN")
_FLAG_TYPES = ("DNF", "DQ", "COURSE_CUT_SUSPECT")


@bp.post("/race-timing/result-flags")
@endpoint("RaceOfficial")
def create_flag():
    body = get_body(("registration_id", "flag_type"))
    reg = get_or_404(db.registrations, body.get("registration_id"))
    flag_type = v_enum(body, "flag_type", _FLAG_TYPES)
    detail = body.get("detail")
    if detail is not None and not isinstance(detail, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "detail must be a string")
    race = db.races.get(reg["race_id"])
    if race is None or race["status"] not in _FLAG_STATES:
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "Result flags require the race in IN_PROGRESS, PROVISIONAL_PUBLISHED or AMENDMENT_OPEN",
        )
    flag = new_entity()
    flag.update(
        {
            "registration_id": reg["id"],
            "flag_type": flag_type,
            "origin": "MANUAL",
            "status": "RAISED",
            "detail": detail,
        }
    )
    db.result_flags[flag["id"]] = flag
    return ok(ser_result_flag(flag), 201)


@bp.get("/race-timing/result-flags/<flag_id>")
@endpoint(*_READERS)
def get_flag(flag_id):
    return ok(ser_result_flag(get_or_404(db.result_flags, flag_id)))


@bp.get("/race-timing/result-flags")
@endpoint(*_READERS)
def list_flags():
    items = list(db.result_flags.values())
    for param in ("registration_id", "flag_type", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [f for f in items if f.get(param) == v]
    return list_page(items, ser_result_flag)


@bp.post("/race-timing/result-flags/<flag_id>/resolve")
@endpoint("RaceOfficial")
def resolve_flag(flag_id):
    flag = get_or_404(db.result_flags, flag_id)
    body = get_body(("outcome",))
    outcome = v_enum(body, "outcome", ("CONFIRMED", "DISMISSED"))
    reg = db.registrations.get(flag["registration_id"])
    race = db.races.get(reg["race_id"]) if reg else None
    if flag["status"] != "RAISED" or race is None or race["status"] not in _FLAG_STATES:
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "Flag must be RAISED and the race in IN_PROGRESS, PROVISIONAL_PUBLISHED or AMENDMENT_OPEN",
        )
    if outcome == "DISMISSED":
        flag["status"] = "DISMISSED"
        touch(flag)
        return ok(ser_result_flag(flag))
    flag["status"] = "CONFIRMED"
    touch(flag)
    # flag cascade C2: only once results exist (race published or in amendment)
    if race["status"] in ("PROVISIONAL_PUBLISHED", "AMENDMENT_OPEN"):
        engine.recompute_race(race, "flag")
    return ok(ser_result_flag(flag))
