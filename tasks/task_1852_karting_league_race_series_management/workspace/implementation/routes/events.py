"""Race events: creation, lifecycle transitions, and grid locking."""
from flask import Blueprint

from errors import (
    raise_error,
    ERR_INVALID_STATE,
    ERR_SEASON_NOT_ACTIVE,
    ERR_DUPLICATE_ROUND,
    ERR_OPEN_INCIDENTS,
    ERR_TECH_NOT_PASSED,
    ERR_ENTRY_FEE_UNPAID,
)
from middleware import authorized, ANY_ROLE
from response import success_object, success_array
from services import core
from services.cascades import cancel_event_cascade
from validate import json_body, v_str, v_int, v_datetime

bp = Blueprint("events", __name__)


def _check_event_creation_gate(season):
    """Event creation requires an ACTIVE season (ERR_SEASON_NOT_ACTIVE); an
    AWARDS_CONCLUDED season is locked outright (ERR_INVALID_STATE)."""
    if season["status"] == "AWARDS_CONCLUDED":
        raise_error(ERR_INVALID_STATE, "season is locked after awards conclusion")
    if season["status"] != "ACTIVE":
        raise_error(ERR_SEASON_NOT_ACTIVE, "season is not ACTIVE")


@bp.post("/seasons/<season_id>/events")
def create_event(season_id):
    authorized(["LeagueAdmin"])
    body = json_body()
    round_number = v_int(body, "round_number", min_val=1)
    date_raw, _dt = v_datetime(body, "event_date")
    track_name = v_str(body, "track_name")
    season = core.must_find("seasons", season_id, "season not found")
    _check_event_creation_gate(season)
    for e in core.db["events"].values():
        if e["season_id"] == season["id"] and e["round_number"] == round_number:
            raise_error(ERR_DUPLICATE_ROUND, "round_number already used in the season")
    event = core.create_record("events", {
        "season_id": season["id"],
        "round_number": round_number,
        "event_date": date_raw,
        "track_name": track_name,
        "status": "SCHEDULED",
    })
    return success_object(core.serialize_event(event), 201)


@bp.get("/seasons/<season_id>/events")
def list_events(season_id):
    authorized(ANY_ROLE)
    season = core.must_find("seasons", season_id, "season not found")
    items = [e for e in core.db["events"].values() if e["season_id"] == season["id"]]
    return success_array([core.serialize_event(e) for e in core.list_sorted(items)])


@bp.get("/events/<event_id>")
def get_event(event_id):
    authorized(ANY_ROLE)
    event = core.must_find("events", event_id, "event not found")
    return success_object(core.serialize_event(event))


def _get_event(event_id):
    return core.must_find("events", event_id, "event not found")


@bp.post("/events/<event_id>/open-registration")
def open_registration(event_id):
    authorized(["LeagueAdmin"])
    event = _get_event(event_id)
    season = core.db["seasons"].get(event["season_id"])
    if season is None or season["status"] != "ACTIVE":
        raise_error(ERR_SEASON_NOT_ACTIVE, "parent season is not ACTIVE")
    if event["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "event is not SCHEDULED")
    event["status"] = "REGISTRATION_OPEN"
    core.touch(event)
    return success_object(core.serialize_event(event))


@bp.post("/events/<event_id>/start")
def start_event(event_id):
    authorized(["RaceDirector"])
    event = _get_event(event_id)
    if event["status"] != "REGISTRATION_OPEN":
        raise_error(ERR_INVALID_STATE, "event is not REGISTRATION_OPEN")
    has_ready_entry = any(
        en["event_id"] == event["id"] and en["status"] in ("TECH_PASSED", "GRID_LOCKED")
        for en in core.db["entries"].values()
    )
    if not has_ready_entry:
        raise_error(ERR_INVALID_STATE, "no entry in TECH_PASSED or GRID_LOCKED")
    event["status"] = "IN_PROGRESS"
    core.touch(event)
    return success_object(core.serialize_event(event))


@bp.post("/events/<event_id>/complete")
def complete_event(event_id):
    authorized(["RaceDirector"])
    event = _get_event(event_id)
    if event["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE, "event is not IN_PROGRESS")
    for sess in core.db["sessions"].values():
        if sess["event_id"] == event["id"] and sess["status"] != "SCORED":
            raise_error(ERR_INVALID_STATE, "not every session is SCORED")
    event["status"] = "COMPLETED"
    core.touch(event)
    return success_object(core.serialize_event(event))


@bp.post("/events/<event_id>/finalize")
def finalize_event(event_id):
    authorized(["RaceDirector"])
    event = _get_event(event_id)
    if event["status"] != "COMPLETED":
        raise_error(ERR_INVALID_STATE, "event is not COMPLETED")
    for inc in core.db["incidents"].values():
        if inc["event_id"] == event["id"] and inc["status"] in core.OPEN_INCIDENT_STATES:
            raise_error(ERR_OPEN_INCIDENTS, "event has open incidents")
    # side effect: every PROVISIONAL/AMENDED result of the event -> FINAL
    session_ids = {
        s["id"] for s in core.db["sessions"].values() if s["event_id"] == event["id"]
    }
    for r in core.db["results"].values():
        if r["session_id"] in session_ids and r["status"] in ("PROVISIONAL", "AMENDED"):
            r["status"] = "FINAL"
            core.touch(r)
    event["status"] = "FINALIZED"
    core.touch(event)
    return success_object(core.serialize_event(event))


@bp.post("/events/<event_id>/cancel")
def cancel_event(event_id):
    authorized(["LeagueAdmin"])
    event = _get_event(event_id)
    if event["status"] not in ("SCHEDULED", "REGISTRATION_OPEN", "IN_PROGRESS"):
        raise_error(ERR_INVALID_STATE, "event cannot be cancelled from its current state")
    cancel_event_cascade(event)
    event["status"] = "CANCELLED"
    core.touch(event)
    return success_object(core.serialize_event(event))


@bp.post("/events/<event_id>/lock-grid")
def lock_grid(event_id):
    """All-or-nothing: every non-WITHDRAWN entry must be TECH_PASSED (state,
    priority 6) and fee-settled (fiscal, priority 10) before any lock is applied."""
    authorized(["RaceDirector"])
    event = _get_event(event_id)
    if event["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE, "event is not IN_PROGRESS")
    active = [
        en for en in core.db["entries"].values()
        if en["event_id"] == event["id"] and en["status"] != "WITHDRAWN"
    ]
    for en in active:
        if en["status"] != "TECH_PASSED":
            raise_error(ERR_TECH_NOT_PASSED, "a non-WITHDRAWN entry is not in TECH_PASSED")
    for en in active:
        if en["fee_status"] != "PAID":
            raise_error(ERR_ENTRY_FEE_UNPAID, "a non-WITHDRAWN entry's fee is not PAID")
    for en in active:
        en["status"] = "GRID_LOCKED"
        core.touch(en)
    core.touch(event)
    return success_object(core.serialize_event(event))
