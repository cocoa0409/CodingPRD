from flask import Blueprint, request

import clock
import db
from db import new_entity, touch
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PROTEST_WINDOW_CLOSED,
    ERR_SOD_VIOLATION,
)
from middleware import endpoint
from response import ok
from serializers import ser_protest
from services import recompute as engine
from util import parse_dt
from validators import get_body, get_or_404, list_page, v_enum, v_str

bp = Blueprint("protests", __name__)

_READERS = ("RaceDirector", "RegistrationClerk", "RaceOfficial")
_ACTIONS = ("EXCLUDE_READ", "REINSTATE_READ", "ADJUST_READ_TIME")


@bp.post("/race-timing/protests")
@endpoint("RegistrationClerk")
def create_protest():
    body = get_body(
        ("race_id", "registration_id", "timing_read_id", "requested_action", "reason")
    )
    # body identifiers resolve left to right
    race = get_or_404(db.races, body.get("race_id"))
    reg = get_or_404(db.registrations, body.get("registration_id"))
    read = get_or_404(db.timing_reads, body.get("timing_read_id"))
    requested_action = v_enum(body, "requested_action", _ACTIONS)
    reason = v_str(body, "reason")

    # the window check runs before the referential checks (strict less-than)
    closes = race["protest_window_closes_at"]
    if closes is None or clock.now_sec() >= closes:
        raise ApiError(
            ERR_PROTEST_WINDOW_CLOSED, 409, "The protest window has closed"
        )

    # referential checks
    if reg["race_id"] != race["id"]:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "registration_id does not belong to race_id"
        )
    has_result = any(
        r["registration_id"] == reg["id"] and r["race_id"] == race["id"]
        for r in db.results.values()
    )
    if not has_result:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "Protest subject must have a result in the race",
        )
    point = db.timing_points.get(read["timing_point_id"])
    if point is None or point["race_id"] != race["id"]:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "timing_read_id does not belong to the race"
        )
    ct_raw = body.get("corrected_timestamp")
    if requested_action == "ADJUST_READ_TIME":
        corrected = parse_dt(ct_raw)
        if corrected is None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "corrected_timestamp is required for ADJUST_READ_TIME",
            )
    else:
        if ct_raw is not None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "corrected_timestamp is only allowed for ADJUST_READ_TIME",
            )
        corrected = None

    protest = new_entity()
    protest.update(
        {
            "race_id": race["id"],
            "registration_id": reg["id"],
            "timing_read_id": read["id"],
            "requested_action": requested_action,
            "corrected_timestamp": corrected,
            "reason": reason,
            "filed_by_user_id": request.user_id,
            "status": "FILED",
            "resolved_by_user_id": None,
        }
    )
    db.protests[protest["id"]] = protest
    return ok(ser_protest(protest), 201)


@bp.get("/race-timing/protests/<protest_id>")
@endpoint(*_READERS)
def get_protest(protest_id):
    return ok(ser_protest(get_or_404(db.protests, protest_id)))


@bp.get("/race-timing/protests")
@endpoint(*_READERS)
def list_protests():
    items = list(db.protests.values())
    for param in ("race_id", "registration_id", "status", "timing_read_id"):
        v = request.args.get(param)
        if v is not None:
            items = [p for p in items if p.get(param) == v]
    return list_page(items, ser_protest)


@bp.post("/race-timing/protests/<protest_id>/resolve")
@endpoint("RaceOfficial")
def resolve_protest(protest_id):
    protest = get_or_404(db.protests, protest_id)
    body = get_body(("outcome",))
    outcome = v_enum(body, "outcome", ("UPHELD", "DISMISSED"))
    race = db.races.get(protest["race_id"])
    # state check first
    if protest["status"] != "FILED" or race is None or race["status"] != "PROVISIONAL_PUBLISHED":
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "Protest must be FILED and the race PROVISIONAL_PUBLISHED",
        )
    # then the duty check
    if request.user_id == protest["filed_by_user_id"]:
        raise ApiError(
            ERR_SOD_VIOLATION,
            403,
            "The protest resolver must differ from the clerk who filed it",
        )
    protest["resolved_by_user_id"] = request.user_id
    if outcome == "DISMISSED":
        protest["status"] = "DISMISSED"
        touch(protest)
        return ok(ser_protest(protest))

    # UPHELD: spawn an already-APPROVED correction and run cascade C1
    protest["status"] = "UPHELD"
    touch(protest)
    corr = new_entity()
    corr.update(
        {
            "race_id": protest["race_id"],
            "timing_read_id": protest["timing_read_id"],
            "kind": protest["requested_action"],
            "corrected_timestamp": protest["corrected_timestamp"],
            "reason": protest["reason"],
            "protest_id": protest["id"],
            "status": "APPROVED",
            "adjudicated_by_user_id": request.user_id,
        }
    )
    db.corrections[corr["id"]] = corr
    engine.apply_correction_cascade(corr, race)
    return ok(ser_protest(protest))
