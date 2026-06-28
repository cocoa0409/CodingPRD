"""ScheduleProgram endpoints (PRD 2.8, 3.7).

Activation uses the closed-with-buffer rule: the new window must be separated by
at least TRANSITION_BUFFER_MIN (5) minutes on BOTH sides from any other ACTIVE
program's window on the same project. Merely touching is NOT enough.
"""

from flask import Blueprint

from common import (
    get_json_body,
    paginate,
    require_fields,
    require_int,
    require_string,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import get_project, get_schedule_program
from middleware import get_auth, require_role
from response import success
from services.calc import TRANSITION_BUFFER_MIN
from services.serialize import ser_schedule_program

bp = Blueprint("schedule_programs", __name__)

READ_ROLES = {"ControlProgrammer", "OperationsAdmin"}


def _validate_window(start, end):
    """ERR_INVALID_WINDOW: end strictly > start; ranges 0..1439 / 1..1440."""
    if not (0 <= start <= 1439):
        raise err("ERR_INVALID_WINDOW", "window_start_min out of range.")
    if not (1 <= end <= 1440):
        raise err("ERR_INVALID_WINDOW", "window_end_min out of range.")
    if not (end > start):
        raise err("ERR_INVALID_WINDOW", "window_end_min must exceed window_start_min.")


@bp.post("/schedule-programs")
def create_schedule_program():
    _, role = get_auth()
    require_role(role, {"ControlProgrammer"})
    body = get_json_body()
    require_fields(
        body, ["project_id", "scene_label", "window_start_min", "window_end_min"]
    )
    project_id = require_string(body, "project_id")
    scene_label = require_string(body, "scene_label")
    start = require_int(body, "window_start_min")
    end = require_int(body, "window_end_min")
    get_project(project_id)
    _validate_window(start, end)

    record = stamp_new(
        {
            "project_id": project_id,
            "scene_label": scene_label,
            "window_start_min": start,
            "window_end_min": end,
            "status": "DRAFT",
        }
    )
    db.schedule_programs[record["id"]] = record
    return success(ser_schedule_program(record), status=201)


@bp.get("/schedule-programs/<sid>")
def read_schedule_program(sid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    s = get_schedule_program(sid)
    return success(ser_schedule_program(s), status=200)


@bp.get("/projects/<pid>/schedule-programs")
def list_project_schedule_programs(pid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    get_project(pid)
    items = [s for s in db.schedule_programs.values() if s["project_id"] == pid]
    data, pagination = paginate(items, ser_schedule_program)
    return success(data, status=200, pagination=pagination)


@bp.post("/schedule-programs/<sid>/activate")
def activate_schedule_program(sid):
    _, role = get_auth()
    require_role(role, {"ControlProgrammer"})
    s = get_schedule_program(sid)
    if s["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Program is not DRAFT.")
    project = db.projects[s["project_id"]]
    if project["commercial_status"] != "INSTALLED":
        raise err("ERR_PROJECT_NOT_INSTALLED", "Project is not INSTALLED.")

    # Closed-with-buffer overlap gate against other ACTIVE programs on the
    # same project. A separation of at least 5 minutes is required on both
    # sides. Two windows [a,b) and [c,d) are "too close" unless one ends at
    # least 5 minutes before the other begins:
    #   compatible iff (s.end + buffer <= other.start) OR (other.end + buffer <= s.start)
    start, end = s["window_start_min"], s["window_end_min"]
    for other in db.schedule_programs.values():
        if (
            other["id"] != sid
            and other["project_id"] == s["project_id"]
            and other["status"] == "ACTIVE"
        ):
            o_start, o_end = other["window_start_min"], other["window_end_min"]
            gap_ok = (
                end + TRANSITION_BUFFER_MIN <= o_start
                or o_end + TRANSITION_BUFFER_MIN <= start
            )
            if not gap_ok:
                raise err(
                    "ERR_SCENE_WINDOW_TOO_CLOSE",
                    "Program window is within the transition buffer of an active program.",
                )

    s["status"] = "ACTIVE"
    touch(s)
    return success(ser_schedule_program(s), status=200)


@bp.post("/schedule-programs/<sid>/disable")
def disable_schedule_program(sid):
    _, role = get_auth()
    require_role(role, {"ControlProgrammer"})
    s = get_schedule_program(sid)
    if s["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Program is not ACTIVE.")
    s["status"] = "DISABLED"
    touch(s)
    return success(ser_schedule_program(s), status=200)
