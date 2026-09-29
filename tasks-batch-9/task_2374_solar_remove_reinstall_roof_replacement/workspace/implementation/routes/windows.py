"""Crew work windows, mobilization buffers and weather aborts (PRD 3.3)."""

import calc
import errors as E
import services
from errors import ApiError
from flask import Blueprint, g
from db import db, new_row, touch
from middleware import PARTY_ROLES, endpoint
from response import ok_row
from routes.helpers import (
    TRADES,
    WINDOW_STATUSES,
    check_frozen,
    get_party,
    get_project,
    get_window,
    invalid_state,
    paged,
    party_type_mismatch,
    resolve_fk,
)
from validation import (
    datetime_field,
    enum_field,
    enum_query,
    get_body,
    int_field,
    str_field,
    str_query,
)

bp = Blueprint("windows", __name__)

READ_ROLES = (
    "ProjectCoordinator",
    "SolarContractor",
    "RoofingContractor",
    "SolarOwner",
    "SystemOwner",
)
CREW_PARTY_TYPES = ("ROOFER", "SOLAR_CONTRACTOR")


def _check_bounds(start_utc, end_utc):
    """Priority 20."""
    if end_utc <= start_utc:
        raise ApiError(
            E.ERR_INVALID_WINDOW_BOUNDS,
            "end_utc must be strictly after start_utc",
            422,
        )


def _check_conflict(party_id, start_utc, end_utc, exclude_id=None):
    """Priority 22: symmetric mobilization-buffer overlap on the same party."""
    party = db.parties.get(party_id)
    buffer_minutes = party["mobilization_buffer_minutes"] if party else 0
    for other in db.windows.values():
        if other["party_id"] != party_id:
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if calc.crew_window_conflict(
            start_utc, end_utc, other["start_utc"], other["end_utc"], buffer_minutes
        ):
            raise ApiError(
                E.ERR_CREW_WINDOW_CONFLICT,
                "the requested interval conflicts with another window on this party",
                409,
            )


@bp.route("/reroof/work-windows", methods=["POST"])
@endpoint("ProjectCoordinator")
def create_window():
    body = get_body()
    project = resolve_fk(body, "project_id", get_project)
    party = resolve_fk(body, "party_id", get_party)
    project_id = str_field(body, "project_id", required=True)
    party_id = str_field(body, "party_id", required=True)
    trade = enum_field(body, "trade", TRADES, required=True)
    start_utc = datetime_field(body, "start_utc", required=True)
    end_utc = datetime_field(body, "end_utc", required=True)
    weather_risk_score = int_field(
        body, "weather_risk_score", required=False, default=0, minimum=0, maximum=100
    )

    # Priority 10
    check_frozen(project)
    # Priority 17
    if party["party_type"] not in CREW_PARTY_TYPES:
        raise party_type_mismatch(
            "party_id must reference a ROOFER or SOLAR_CONTRACTOR party"
        )
    _check_bounds(start_utc, end_utc)
    _check_conflict(party_id, start_utc, end_utc)

    snapshot = services.project_snapshot(project)
    window = new_row(
        {
            "project_id": project_id,
            "party_id": party_id,
            "trade": trade,
            "start_utc": start_utc,
            "end_utc": end_utc,
            "weather_risk_score": weather_risk_score,
            "status": "SCHEDULED",
            "supersedes_window_id": None,
            "abort_reason": None,
            "actual_start_utc": None,
            "actual_end_utc": None,
        }
    )
    db.windows[window["id"]] = window
    services.rollup_project(project)
    services.commit_project(project, snapshot)
    return ok_row(window, 201)


@bp.route("/reroof/work-windows/<window_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_window(window_id):
    return ok_row(get_window(window_id))


@bp.route("/reroof/work-windows", methods=["GET"])
@endpoint(*READ_ROLES)
def list_windows():
    project_id = str_query("project_id")
    party_id = str_query("party_id")
    status = enum_query("status", WINDOW_STATUSES)
    supersedes = str_query("supersedes_window_id")

    rows = []
    for window in db.windows.values():
        if project_id is not None and window["project_id"] != project_id:
            continue
        if party_id is not None and window["party_id"] != party_id:
            continue
        if status is not None and window["status"] != status:
            continue
        if supersedes is not None and window["supersedes_window_id"] != supersedes:
            continue
        rows.append(window)
    return paged(rows)


@bp.route("/reroof/work-windows/<window_id>/status", methods=["POST"])
@endpoint("ProjectCoordinator", "RoofingContractor", "SolarContractor")
def advance_window(window_id):
    window = get_window(window_id)
    project = db.projects.get(window["project_id"])
    body = get_body()
    action = enum_field(
        body, "action", ("START", "COMPLETE", "WEATHER_ABORT"), required=True
    )
    abort_reason = str_field(body, "abort_reason", required=False, default=None)
    weather_risk_score = int_field(
        body, "weather_risk_score", required=False, default=None, minimum=0, maximum=100
    )
    if action == "WEATHER_ABORT" and abort_reason is None:
        raise E.invalid_request("field 'abort_reason' is required for a WEATHER_ABORT")

    # Priority 6: a crew-driven status change acts on its own window.
    if g.get("actor_role") in PARTY_ROLES and g.get("actor_id") != window["party_id"]:
        raise ApiError(
            E.ERR_PARTY_NOT_ON_PROJECT,
            "only the window's own crew party may advance it",
            403,
        )

    now = db.now()
    # Priority 8
    if action == "START":
        if window["status"] != "SCHEDULED":
            raise invalid_state("cannot START a window in %s" % window["status"])
        if now < window["start_utc"]:
            raise invalid_state(
                "a window cannot be started before its start_utc"
            )
        # Priority 10
        check_frozen(project)
    elif action == "COMPLETE":
        if window["status"] != "IN_PROGRESS":
            raise invalid_state("cannot COMPLETE a window in %s" % window["status"])
    else:
        if window["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            raise invalid_state(
                "cannot WEATHER_ABORT a window in %s" % window["status"]
            )

    snapshot = services.project_snapshot(project)
    if weather_risk_score is not None:
        window["weather_risk_score"] = weather_risk_score

    if action == "START":
        window["status"] = "IN_PROGRESS"
        window["actual_start_utc"] = now
    elif action == "COMPLETE":
        window["status"] = "COMPLETED"
        window["actual_end_utc"] = now
    else:
        window["status"] = "WEATHER_ABORTED"
        window["actual_end_utc"] = now
        window["abort_reason"] = abort_reason
        project["weather_abort_count"] += 1
    touch(window)

    services.rollup_project(project)
    services.commit_project(project, snapshot)
    return ok_row(window)


@bp.route("/reroof/work-windows/<window_id>/reschedule", methods=["POST"])
@endpoint("ProjectCoordinator")
def reschedule_window(window_id):
    original = get_window(window_id)
    project = db.projects.get(original["project_id"])
    body = get_body()
    party = resolve_fk(body, "party_id", get_party)
    start_utc = datetime_field(body, "start_utc", required=True)
    end_utc = datetime_field(body, "end_utc", required=True)
    weather_risk_score = int_field(
        body, "weather_risk_score", required=False, default=None, minimum=0, maximum=100
    )

    # Priority 8
    if original["status"] != "WEATHER_ABORTED":
        raise invalid_state(
            "only a WEATHER_ABORTED window may be rescheduled, not one in %s"
            % original["status"]
        )

    party_id = party["id"] if party is not None else original["party_id"]
    _check_bounds(start_utc, end_utc)
    _check_conflict(party_id, start_utc, end_utc, exclude_id=original["id"])

    snapshot = services.project_snapshot(project)
    original["status"] = "SUPERSEDED"
    touch(original)

    replacement = new_row(
        {
            "project_id": original["project_id"],
            "party_id": party_id,
            "trade": original["trade"],
            "start_utc": start_utc,
            "end_utc": end_utc,
            "weather_risk_score": (
                weather_risk_score
                if weather_risk_score is not None
                else original["weather_risk_score"]
            ),
            "status": "SCHEDULED",
            "supersedes_window_id": original["id"],
            "abort_reason": None,
            "actual_start_utc": None,
            "actual_end_utc": None,
        }
    )
    db.windows[replacement["id"]] = replacement

    services.rollup_project(project)
    services.commit_project(project, snapshot)
    return ok_row(replacement, 201)
