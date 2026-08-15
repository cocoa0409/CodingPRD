"""TimingRecord + Result endpoints."""
from flask import Blueprint, request

import db
from errors import (ApiError, ERR_VALIDATION, ERR_INVALID_STATE, ERR_STALE_RESULT_VERSION,
                    not_found)
from middleware import require_roles
from response import success_object, success_list, paginate
from services.core import replay_result, recompute_ranks, recompute_totals
from util import stamp_common, touch, require_fields, require_enum, require_int, parse_dt

bp = Blueprint("timing", __name__)

ALL = ("RaceDirector", "PermitCoordinator", "Referee", "Timer", "VolunteerCoordinator", "Athlete")
DISCIPLINES = ("SWIM", "T1", "BIKE", "T2", "FINISH")
CORRECTION_DISCIPLINES = ("SWIM", "T1", "BIKE", "T2", "RUN")


def get_reg_or_404(reg_id):
    r = db.registrations.get(reg_id)
    if not r:
        raise not_found("registration not found")
    return r


def get_record_or_404(tid):
    t = db.timing_records.get(tid)
    if not t:
        raise not_found("timing record not found")
    return t


def get_result_or_404(rid):
    r = db.results.get(rid)
    if not r:
        raise not_found("result not found")
    return r


def _result_for_registration(reg_id):
    return next((r for r in db.results.values() if r["registration_id"] == reg_id), None)


@bp.post("/registrations/<reg_id>/timing-records")
def create_timing_record(reg_id):
    require_roles("Timer")
    reg = get_reg_or_404(reg_id)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["discipline", "recorded_at"])
    discipline = require_enum(body["discipline"], DISCIPLINES, "discipline")
    parse_dt(body["recorded_at"])
    t = stamp_common({
        "registration_id": reg["id"],
        "discipline": discipline,
        "recorded_at": body["recorded_at"],
        "status": "RECORDED",
    })
    db.timing_records[t["id"]] = t
    return success_object(t, status=201)


@bp.get("/registrations/<reg_id>/timing-records")
def list_timing_records(reg_id):
    require_roles(*ALL)
    reg = get_reg_or_404(reg_id)
    items = [t for t in db.timing_records.values() if t["registration_id"] == reg["id"]]
    discipline = request.args.get("discipline")
    if discipline:
        items = [t for t in items if t["discipline"] == discipline]
    page, limit, offset, total = paginate(items, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/timing-records/<tid>")
def get_timing_record(tid):
    require_roles(*ALL)
    return success_object(get_record_or_404(tid))


@bp.post("/timing-records/<tid>/validate")
def validate_record(tid):
    require_roles("Timer")
    t = get_record_or_404(tid)
    reg = db.registrations[t["registration_id"]]
    if t["status"] != "RECORDED":
        raise ApiError(ERR_INVALID_STATE, f"cannot validate from {t['status']}", 409)
    if reg["status"] not in ("RACING", "FINISHED"):
        raise ApiError(ERR_INVALID_STATE,
                       f"registration must be RACING or FINISHED, is {reg['status']}", 409)
    t["status"] = "VALIDATED"
    touch(t)

    result = _result_for_registration(reg["id"])
    if result:
        replay_result(result)
        if t["discipline"] == "FINISH" and reg["status"] == "RACING":
            reg["status"] = "FINISHED"
            touch(reg)
        touch(result)
        recompute_ranks(reg["event_id"])
    return success_object(t)


@bp.post("/timing-records/<tid>/invalidate")
def invalidate_record(tid):
    require_roles("Timer")
    t = get_record_or_404(tid)
    reg = db.registrations[t["registration_id"]]
    if t["status"] not in ("RECORDED", "VALIDATED"):
        raise ApiError(ERR_INVALID_STATE, f"cannot invalidate from {t['status']}", 409)
    was_validated_finish = (t["status"] == "VALIDATED" and t["discipline"] == "FINISH")
    t["status"] = "INVALIDATED"
    touch(t)

    result = _result_for_registration(reg["id"])
    if result:
        replay_result(result)
        if was_validated_finish and reg["status"] == "FINISHED":
            reg["status"] = "RACING"
            touch(reg)
        touch(result)
        recompute_ranks(reg["event_id"])
    return success_object(t)


@bp.get("/events/<event_id>/results")
def list_results(event_id):
    require_roles(*ALL)
    ev = db.events.get(event_id)
    if not ev:
        raise not_found("event not found")
    reg_by_id = {r["id"]: r for r in db.registrations.values() if r["event_id"] == event_id}
    items = [res for res in db.results.values() if res["registration_id"] in reg_by_id]
    reg_filter = request.args.get("registration_id")
    division = request.args.get("division")
    if reg_filter:
        items = [r for r in items if r["registration_id"] == reg_filter]
    if division:
        items = [r for r in items if reg_by_id[r["registration_id"]]["division"] == division]
    page, limit, offset, total = paginate(items, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/registrations/<reg_id>/results")
def registration_results(reg_id):
    require_roles(*ALL)
    reg = get_reg_or_404(reg_id)
    result = _result_for_registration(reg["id"])
    items = [result] if result else []
    page, limit, offset, total = paginate(items, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/results/<rid>")
def get_result(rid):
    require_roles(*ALL)
    return success_object(get_result_or_404(rid))


@bp.post("/results/<rid>/corrections")
def correct_result(rid):
    require_roles("Timer")
    result = get_result_or_404(rid)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["expected_result_version", "discipline", "corrected_seconds"])
    expected = require_int(body["expected_result_version"], "expected_result_version")
    discipline = require_enum(body["discipline"], CORRECTION_DISCIPLINES, "discipline")
    corrected = require_int(body["corrected_seconds"], "corrected_seconds")

    if result["status"] != "OFFICIAL":
        raise ApiError(ERR_INVALID_STATE, "corrections apply only to OFFICIAL results", 409)
    if expected != result["version"]:
        raise ApiError(ERR_STALE_RESULT_VERSION, "stale result version", 412)

    field_map = {
        "SWIM": "swim_seconds", "T1": "t1_seconds", "BIKE": "bike_seconds",
        "T2": "t2_seconds", "RUN": "run_seconds",
    }
    result[field_map[discipline]] = corrected
    splits = [result["swim_seconds"], result["t1_seconds"], result["bike_seconds"],
              result["t2_seconds"], result["run_seconds"]]
    if None not in splits:
        result["provisional_total_seconds"] = sum(splits)
    else:
        result["provisional_total_seconds"] = None
    recompute_totals(result)
    touch(result)
    reg = db.registrations[result["registration_id"]]
    recompute_ranks(reg["event_id"])
    return success_object(result)
