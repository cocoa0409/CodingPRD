"""DryingSession endpoints: inline projections, finish gate, lab results, redry."""
from flask import Blueprint

import db
from db import store, touch
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import ok, paginate
from services import calc
from validation import parse_body, require_path_entity

bp = Blueprint("drying", __name__)


@bp.get("/drying-sessions")
def list_sessions():
    get_context()
    require_roles(ALL_ROLES)
    rows = list(store.drying_sessions.values())
    rows = paginate.filter(rows, "run_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/drying-sessions/<session_id>")
def get_session(session_id):
    get_context()
    require_roles(ALL_ROLES)
    return ok(require_path_entity(store.drying_sessions, session_id,
                                  "ERR_DRYING_SESSION_NOT_FOUND"))


@bp.post("/drying-sessions/<session_id>/inline-readings")
def inline_reading(session_id):
    get_context()
    require_roles(["ProductionOperator"])
    session = require_path_entity(store.drying_sessions, session_id,
                                  "ERR_DRYING_SESSION_NOT_FOUND")
    if session["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Inline readings require an IN_PROGRESS session")
    session["latest_inline_moisture_pct"] = calc.project_moisture(session, db.clock_now())
    touch(session)
    return ok(session)


@bp.post("/drying-sessions/<session_id>/finish")
def finish_session(session_id):
    get_context()
    require_roles(["ProductionOperator"])
    session = require_path_entity(store.drying_sessions, session_id,
                                  "ERR_DRYING_SESSION_NOT_FOUND")
    if session["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "finish requires an IN_PROGRESS session")
    elapsed = calc.elapsed_hours(session, db.clock_now(), quantize=False)
    if elapsed < db.dec(session["required_hours"]):
        raise ApiError("ERR_DRYING_INCOMPLETE", 409,
                       "Elapsed hours have not reached required_hours")
    session["status"] = "AWAITING_LAB"
    touch(session)
    return ok(session)


@bp.post("/drying-sessions/<session_id>/lab-results")
def session_lab_results(session_id):
    get_context()
    require_roles(["QATechnician"])
    session = require_path_entity(store.drying_sessions, session_id,
                                  "ERR_DRYING_SESSION_NOT_FOUND")
    body = parse_body({"lab_moisture_pct": ("number", True, None)}, allow_empty=False)
    if session["status"] != "AWAITING_LAB":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Lab results require an AWAITING_LAB session")
    session["latest_lab_moisture_pct"] = body["lab_moisture_pct"]
    if db.dec(body["lab_moisture_pct"]) <= db.dec(session["target_moisture_pct"]):
        session["status"] = "CONFIRMED"  # inclusive boundary passes
    else:
        session["status"] = "FAILED"
    touch(session)
    return ok(session)


@bp.post("/drying-sessions/<session_id>/redry")
def redry_session(session_id):
    get_context()
    require_roles(["ProductionOperator"])
    session = require_path_entity(store.drying_sessions, session_id,
                                  "ERR_DRYING_SESSION_NOT_FOUND")
    if session["status"] != "FAILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a FAILED session can be redried")
    session["status"] = "IN_PROGRESS"
    session["redry_count"] += 1
    session["required_hours"] += calc.REMEDIAL_HOURS
    # drying_started_at is untouched: elapsed keeps accruing from the first start.
    touch(session)
    return ok(session)
