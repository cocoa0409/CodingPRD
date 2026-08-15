"""SurveyInstrument, SurveyWindow, SurveyResponse endpoints."""
from flask import Blueprint, request

from db import DB, clock_now, fmt_iso, new_id
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import close_window_manual, get_or_404
from util import (
    as_enum,
    as_int,
    as_str,
    body,
    paginate,
    pagination,
    parse_dt,
    required,
    stamp_new,
    touch,
)

bp = Blueprint("surveys", __name__)

STAKEHOLDER_GROUPS = {"STUDENTS", "PARENTS", "STAFF", "BOARD"}


def instrument_view(s):
    return {k: v for k, v in s.items() if not k.startswith("_")}


def window_view(w):
    return {k: v for k, v in w.items() if not k.startswith("_")}


def response_view(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


# --- SurveyInstrument -------------------------------------------------------

@bp.post("/accreditation/survey-instruments")
def create_instrument():
    auth(["AccreditationOfficer"])
    data = body()
    group = as_enum(
        required(data, "stakeholder_group"), "stakeholder_group", STAKEHOLDER_GROUPS
    )
    title = as_str(required(data, "title"), "title")
    min_pct = as_int(required(data, "min_participation_pct"), "min_participation_pct")
    if min_pct < 1 or min_pct > 100:
        raise ApiError("ERR_VALIDATION", 400, "min_participation_pct must be in 1..100")
    record = {
        "id": new_id(),
        "stakeholder_group": group,
        "title": title,
        "min_participation_pct": min_pct,
    }
    stamp_new(record, with_version=True)
    DB["instruments"][record["id"]] = record
    return ok(instrument_view(record), status=201)


@bp.get("/accreditation/survey-instruments")
def list_instruments():
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    limit, offset = pagination()
    rows = sorted(DB["instruments"].values(), key=lambda s: s["created_at"])
    group = request.args.get("stakeholder_group")
    if group:
        rows = [r for r in rows if r["stakeholder_group"] == group]
    page, total = paginate(rows, limit, offset)
    return ok_list([instrument_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/survey-instruments/<id>")
def get_instrument(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    row = get_or_404("instruments", id, "SurveyInstrument")
    return ok(instrument_view(row))


@bp.get("/accreditation/survey-instruments/<id>/survey-windows")
def list_instrument_windows(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    get_or_404("instruments", id, "SurveyInstrument")
    limit, offset = pagination()
    rows = [w for w in DB["survey_windows"].values() if w["instrument_id"] == id]
    rows.sort(key=lambda w: w["created_at"])
    page, total = paginate(rows, limit, offset)
    return ok_list([window_view(r) for r in page], total, limit, offset)


# --- SurveyWindow -----------------------------------------------------------

@bp.post("/accreditation/terms/<id>/survey-windows")
def create_window(id):
    auth(["AccreditationOfficer"])
    term = get_or_404("terms", id, "AccreditationTerm")
    data = body()
    campus_id = required(data, "campus_id")
    instrument_id = required(data, "instrument_id")
    opens_at_raw = required(data, "opens_at")
    closes_at_raw = required(data, "closes_at")
    eligible_count = as_int(required(data, "eligible_count"), "eligible_count")
    if eligible_count < 1:
        raise ApiError("ERR_VALIDATION", 400, "eligible_count must be >= 1")
    opens_dt = parse_dt(opens_at_raw, "opens_at")
    closes_dt = parse_dt(closes_at_raw, "closes_at")
    if closes_dt <= opens_dt:
        raise ApiError(
            "ERR_VALIDATION", 400, "closes_at must be strictly after opens_at"
        )
    # Referential integrity: campus belongs to term's system; instrument exists.
    campus = DB["campuses"].get(campus_id)
    if campus is None or campus["system_id"] != term["system_id"]:
        raise ApiError(
            "ERR_REFERENTIAL_INTEGRITY",
            422,
            "campus_id does not belong to the term's system",
        )
    instrument = DB["instruments"].get(instrument_id)
    if instrument is None:
        raise ApiError(
            "ERR_REFERENTIAL_INTEGRITY", 422, "instrument_id does not exist"
        )
    # Uniqueness: one window per (term, campus, instrument).
    for w in DB["survey_windows"].values():
        if (
            w["term_id"] == id
            and w["campus_id"] == campus_id
            and w["instrument_id"] == instrument_id
        ):
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE",
                409,
                "A survey window already exists for this (term, campus, instrument)",
            )
    record = {
        "id": new_id(),
        "term_id": id,
        "campus_id": campus_id,
        "instrument_id": instrument_id,
        "opens_at": fmt_iso(opens_dt),
        "closes_at": fmt_iso(closes_dt),
        "eligible_count": eligible_count,
        "response_count": 0,
        "status": "SCHEDULED",
        "_opens_at_dt": opens_dt,
        "_closes_at_dt": closes_dt,
    }
    stamp_new(record, with_version=True)
    DB["survey_windows"][record["id"]] = record
    return ok(window_view(record), status=201)


@bp.get("/accreditation/terms/<id>/survey-windows")
def list_term_windows(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    get_or_404("terms", id, "AccreditationTerm")
    limit, offset = pagination()
    rows = [w for w in DB["survey_windows"].values() if w["term_id"] == id]
    rows.sort(key=lambda w: w["created_at"])
    campus_id = request.args.get("campus_id")
    status = request.args.get("status")
    if campus_id:
        rows = [r for r in rows if r["campus_id"] == campus_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([window_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/survey-windows/<id>")
def get_window(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    row = get_or_404("survey_windows", id, "SurveyWindow")
    return ok(window_view(row))


@bp.post("/accreditation/survey-windows/<id>/close")
def close_window(id):
    auth(["AccreditationOfficer"])
    window = get_or_404("survey_windows", id, "SurveyWindow")
    if window["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Window is not OPEN")
    if clock_now() < window["_opens_at_dt"]:
        raise ApiError(
            "ERR_TEMPORAL_WINDOW_VIOLATION",
            422,
            "Current time is before opens_at",
        )
    close_window_manual(window)
    return ok(window_view(window))


@bp.post("/accreditation/survey-windows/<id>/invalidate")
def invalidate_window(id):
    auth(["AccreditationOfficer"])
    window = get_or_404("survey_windows", id, "SurveyWindow")
    if window["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Window is not SCHEDULED")
    window["status"] = "INVALIDATED"
    touch(window)
    return ok(window_view(window))


# --- SurveyResponse ---------------------------------------------------------

@bp.post("/accreditation/survey-windows/<id>/responses")
def submit_response(id):
    auth(["Anonymous"])
    window = get_or_404("survey_windows", id, "SurveyWindow")
    data = body()
    token = as_str(required(data, "respondent_token"), "respondent_token")
    if window["status"] != "OPEN":
        raise ApiError(
            "ERR_TEMPORAL_WINDOW_VIOLATION",
            422,
            "Window is not OPEN",
        )
    # Token uniqueness per window.
    for r in DB["survey_responses"].values():
        if r["window_id"] == id and r["respondent_token"] == token:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE",
                409,
                "respondent_token already used for this window",
            )
    record = {
        "id": new_id(),
        "window_id": id,
        "respondent_token": token,
        "submitted_at": fmt_iso(clock_now()),
    }
    # SurveyResponse carries id and created_at only (PRD 2.4).
    stamp_new(record, with_version=False)
    DB["survey_responses"][record["id"]] = record
    window["response_count"] += 1
    touch(window)
    return ok(response_view(record), status=201)


@bp.get("/accreditation/survey-windows/<id>/responses")
def list_responses(id):
    auth(["AccreditationOfficer", "AccreditationCommission"])
    get_or_404("survey_windows", id, "SurveyWindow")
    limit, offset = pagination()
    rows = [r for r in DB["survey_responses"].values() if r["window_id"] == id]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return ok_list([response_view(r) for r in page], total, limit, offset)
