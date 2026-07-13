"""Participant registration, demographics, deactivation, contribution statement."""
import calendar
from datetime import datetime, timezone

from flask import Blueprint, request

from store import db, base_common, touch
from core import (
    require_actor, authorize, get_body, ok_object,
    req_str, req_enum, req_bool, opt_int, err, parse_dt, round_half_up,
)
from lookups import get_participant
from serializers import ser_participant, ser_reservation

bp = Blueprint("people", __name__)

GENDER = {"FEMALE", "MALE", "OTHER", "DECLINED"}
ETHNICITY = {"HISPANIC", "NON_HISPANIC", "DECLINED"}
RACE = {"WHITE", "BLACK", "ASIAN", "NATIVE", "PACIFIC", "MULTI", "DECLINED"}
POVERTY = {"BELOW", "AT_OR_ABOVE", "DECLINED"}

CONGREGATE_MEAL_UNIT_COST = 850
CONTRIBUTION_RATE_NUM = 15
CONTRIBUTION_RATE_DEN = 100


@bp.post("/participants")
def create_participant():
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator"})
    body = get_body()
    full_name = req_str(body, "full_name")
    birth_raw = req_str(body, "birth_date")
    parse_dt(birth_raw, "birth_date")  # shape-validate
    rec = base_common()
    rec.update({
        "full_name": full_name,
        "birth_date": birth_raw,
        "gender": req_enum(body, "gender", GENDER),
        "ethnicity": req_enum(body, "ethnicity", ETHNICITY),
        "race": req_enum(body, "race", RACE),
        "poverty_status": req_enum(body, "poverty_status", POVERTY),
        "lives_alone": req_bool(body, "lives_alone"),
        "rural": req_bool(body, "rural"),
        "veteran": req_bool(body, "veteran"),
        "disability_count": opt_int(body, "disability_count", 0, minimum=0),
        "status": "ACTIVE",
        "funded_cents": 0,
    })
    db.participants[rec["id"]] = rec
    return ok_object(ser_participant(rec), 201)


@bp.get("/participants/<pid>")
def get_participant_route(pid):
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator", "Participant", "Auditor"})
    rec = get_participant(pid)
    return ok_object(ser_participant(rec))


@bp.post("/participants/<pid>/deactivate")
def deactivate_participant(pid):
    actor = require_actor()
    authorize(actor, {"CenterAdmin"})
    rec = get_participant(pid)
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Participant is not ACTIVE")
    rec["status"] = "INACTIVE"
    # CASCADE: cancel this participant's CONFIRMED meal reservations, free seats.
    for mr in db.reservations.values():
        if mr["participant_id"] == pid and mr["status"] == "CONFIRMED":
            mr["status"] = "CANCELLED"
            touch(mr)
            day = db.service_days.get(mr["service_day_id"])
            if day is not None:
                day["reserved_count"] -= 1
                touch(day)
    touch(rec)
    return ok_object(ser_participant(rec))


@bp.get("/participants/<pid>/contribution-statement")
def contribution_statement(pid):
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator", "Participant", "Auditor"})
    rec = get_participant(pid)
    month = request.args.get("month")
    if not month:
        raise err("ERR_VALIDATION", "Missing 'month' parameter")
    try:
        y_s, m_s = month.split("-")
        year = int(y_s)
        mon = int(m_s)
        if mon < 1 or mon > 12 or len(m_s) != 2 or len(y_s) != 4:
            raise ValueError
    except (ValueError, AttributeError):
        raise err("ERR_VALIDATION", "month must be in YYYY-MM form")
    start = datetime(year, mon, 1, 0, 0, 0, tzinfo=timezone.utc)
    last_day = calendar.monthrange(year, mon)[1]
    end = datetime(year, mon, last_day, 23, 59, 59, tzinfo=timezone.utc)

    per_meal = round_half_up(
        CONGREGATE_MEAL_UNIT_COST * CONTRIBUTION_RATE_NUM, CONTRIBUTION_RATE_DEN
    )
    meal_count = 0
    total = 0
    for mr in db.reservations.values():
        if mr["participant_id"] != pid or mr["status"] != "CHECKED_IN":
            continue
        day = db.service_days.get(mr["service_day_id"])
        if day is None:
            continue
        sd = parse_dt(day["service_date"], "service_date")
        if start <= sd <= end:
            meal_count += 1
            total += per_meal  # pinned: round per meal first, then sum
    return ok_object(
        {"total_suggested_contribution_cents": total, "meal_count": meal_count}
    )
