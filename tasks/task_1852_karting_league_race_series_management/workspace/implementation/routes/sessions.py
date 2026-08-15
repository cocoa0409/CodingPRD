"""Race sessions, result batches (OCC-guarded), and scoring."""
from flask import Blueprint

from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_SESSION_NOT_CLOSED,
    ERR_RESULTS_INCOMPLETE,
    ERR_DUPLICATE_RESULT,
)
from middleware import authorized, ANY_ROLE
from response import success_object, success_array
from services import core
from services.calculations import recompute_session_points
from validate import json_body, v_enum, v_int, is_int

bp = Blueprint("sessions", __name__)

SESSION_TYPES = {"PRACTICE", "QUALIFYING", "HEAT", "MAIN"}
SESSION_STATUSES = {"SCHEDULED", "OPEN", "CLOSED", "SCORED"}


@bp.post("/events/<event_id>/sessions")
def create_session(event_id):
    authorized(["RaceDirector"])
    body = json_body()
    session_type = v_enum(body, "session_type", SESSION_TYPES)
    sequence = v_int(body, "sequence", min_val=1)
    expected = body.get("expected_event_version")
    if not is_int(expected):
        raise_error(ERR_INVALID_REQUEST, "expected_event_version is required and must be an integer")
    event = core.must_find("events", event_id, "event not found")
    # priority 5: OCC on the parent event's version
    if expected != event["version"]:
        raise_error(ERR_STALE_VERSION, "expected_event_version does not match the event's current version")
    if event["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE, "event is not IN_PROGRESS")
    session = core.create_record("sessions", {
        "event_id": event["id"],
        "session_type": session_type,
        "sequence": sequence,
        "status": "SCHEDULED",
    })
    # session creation advances the parent event's version (PRD 2.6)
    core.touch(event)
    return success_object(core.serialize_session(session), 201)


@bp.get("/events/<event_id>/sessions")
def list_sessions(event_id):
    authorized(ANY_ROLE)
    event = core.must_find("events", event_id, "event not found")
    items = [s for s in core.db["sessions"].values() if s["event_id"] == event["id"]]
    return success_array([core.serialize_session(s) for s in core.list_sorted(items)])


@bp.get("/sessions/<session_id>")
def get_session(session_id):
    authorized(ANY_ROLE)
    session = core.must_find("sessions", session_id, "session not found")
    return success_object(core.serialize_session(session))


@bp.patch("/sessions/<session_id>")
def patch_session(session_id):
    authorized(["RaceDirector"])
    body = json_body()
    target = v_enum(body, "status", SESSION_STATUSES)
    session = core.must_find("sessions", session_id, "session not found")
    if session["status"] == "SCHEDULED" and target == "OPEN":
        event = core.db["events"].get(session["event_id"])
        if event is None or event["status"] != "IN_PROGRESS":
            raise_error(ERR_INVALID_STATE, "parent event is not IN_PROGRESS")
    elif session["status"] == "OPEN" and target == "CLOSED":
        pass
    else:
        raise_error(
            ERR_INVALID_STATE,
            f"session status transition {session['status']} -> {target} is not permitted",
        )
    session["status"] = target
    core.touch(session)
    return success_object(core.serialize_session(session))


@bp.post("/sessions/<session_id>/results")
def submit_results(session_id):
    authorized(["RaceDirector"])
    body = json_body()
    rows = body.get("results")
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise_error(ERR_INVALID_REQUEST, "results must be an array of objects")
    expected = body.get("expected_session_version")
    if not is_int(expected):
        raise_error(ERR_INVALID_REQUEST, "expected_session_version is required and must be an integer")
    # per-row well-formedness (priority 3)
    for row in rows:
        entry_id = row.get("entry_id")
        if not isinstance(entry_id, str):
            raise_error(ERR_INVALID_REQUEST, "each result row requires an entry_id string")
        if not is_int(row.get("finish_position")) or row["finish_position"] < 1:
            raise_error(ERR_INVALID_REQUEST, "finish_position must be an integer >= 1")
        if not is_int(row.get("best_lap_ms")) or row["best_lap_ms"] <= 0:
            raise_error(ERR_INVALID_REQUEST, "best_lap_ms must be an integer > 0")
        if not is_int(row.get("total_time_ms")) or row["total_time_ms"] <= 0:
            raise_error(ERR_INVALID_REQUEST, "total_time_ms must be an integer > 0")

    # priority 4: existence and scope
    session = core.must_find("sessions", session_id, "session not found")
    entries = []
    for row in rows:
        entry = core.find("entries", row["entry_id"])
        if entry is None or entry["event_id"] != session["event_id"]:
            raise_error(ERR_NOT_FOUND, "result row references an entry outside the session's event")
        entries.append(entry)

    # priority 5: OCC on the session's version
    if expected != session["version"]:
        raise_error(ERR_STALE_VERSION, "expected_session_version does not match the session's current version")

    # priority 6: state — results only while CLOSED; rows must be GRID_LOCKED entries
    if session["status"] != "CLOSED":
        raise_error(ERR_INVALID_STATE, "session is not CLOSED")
    for entry in entries:
        if entry["status"] != "GRID_LOCKED":
            raise_error(ERR_INVALID_STATE, "result row entry is not GRID_LOCKED")

    # priority 9: one result row per entry per submission
    seen = set()
    for row in rows:
        if row["entry_id"] in seen:
            raise_error(ERR_DUPLICATE_RESULT, "result batch contains two rows for the same entry")
        seen.add(row["entry_id"])

    # supersede: discard the prior batch wholesale, record new PROVISIONAL rows
    stale_ids = [rid for rid, r in core.db["results"].items() if r["session_id"] == session["id"]]
    for rid in stale_ids:
        del core.db["results"][rid]
    created = []
    for row in rows:
        rec = core.create_record("results", {
            "session_id": session["id"],
            "entry_id": row["entry_id"],
            "finish_position": row["finish_position"],
            "best_lap_ms": row["best_lap_ms"],
            "total_time_ms": row["total_time_ms"],
            "penalty_seconds_applied": 0,
            "is_fastest_lap": False,
            "points_awarded": 0,
            "status": "PROVISIONAL",
        })
        created.append(rec)
    core.touch(session)
    return success_array([core.serialize_result(r) for r in created], 201)


@bp.post("/sessions/<session_id>/score")
def score_session(session_id):
    authorized(["RaceDirector"])
    session = core.must_find("sessions", session_id, "session not found")
    if session["status"] != "CLOSED":
        raise_error(ERR_SESSION_NOT_CLOSED, "session is not CLOSED")
    grid_locked = [
        en for en in core.db["entries"].values()
        if en["event_id"] == session["event_id"] and en["status"] == "GRID_LOCKED"
    ]
    result_entry_ids = {
        r["entry_id"] for r in core.db["results"].values() if r["session_id"] == session["id"]
    }
    for en in grid_locked:
        if en["id"] not in result_entry_ids:
            raise_error(ERR_RESULTS_INCOMPLETE, "every GRID_LOCKED entry must hold a result row")
    recompute_session_points(session, rerank=False)
    session["status"] = "SCORED"
    core.touch(session)
    return success_object(core.serialize_session(session))


@bp.get("/sessions/<session_id>/results")
def list_session_results(session_id):
    authorized(ANY_ROLE)
    session = core.must_find("sessions", session_id, "session not found")
    items = [r for r in core.db["results"].values() if r["session_id"] == session["id"]]
    return success_array([core.serialize_result(r) for r in core.list_sorted(items)])


@bp.get("/entries/<entry_id>/results")
def list_entry_results(entry_id):
    authorized(ANY_ROLE)
    entry = core.must_find("entries", entry_id, "entry not found")
    items = [r for r in core.db["results"].values() if r["entry_id"] == entry["id"]]
    return success_array([core.serialize_result(r) for r in core.list_sorted(items)])
