"""BoothAssignment + inspection routes."""

from flask import Blueprint, request
import db
import validators as V
from middleware import require_roles
from response import success_object, success_list
from pagination import parse_pagination, paginate
from serializers import booth_assignment_out, project_out
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL, ERR_INVALID_WINDOW, ERR_OUTSIDE_WINDOW,
    ERR_BOOTH_TAKEN,
)

bp = Blueprint("booths", __name__)

_VALID_RESULT = {"PASS", "FAIL"}


def _touch(e):
    e["updated_at"] = db.now_display_iso()
    e["version"] += 1


@bp.route("/science-fair/projects/<pid>/booth-assignments", methods=["POST"])
def create_booth_assignment(pid):
    body = V.get_json_body()
    V.require_fields(body, ["hall", "booth_number",
                            "inspection_window_start",
                            "inspection_window_end"])
    hall = V.req_str(body, "hall")
    booth_number = V.req_int(body, "booth_number")
    win_start = V.req_str(body, "inspection_window_start")
    win_end = V.req_str(body, "inspection_window_end")

    require_roles("OperationsLead")

    project = db.projects.get(pid)
    if project is None:
        raise_err(ERR_NOT_FOUND, f"Project not found: {pid}")

    if project["registration_status"] == "WITHDRAWN":
        raise_err(ERR_ALREADY_TERMINAL, "Project is WITHDRAWN (terminal)")

    # State: project must be CONFIRMED and NOT_SCHEDULED
    if project["registration_status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE,
                  "Booth assignment requires project registration_status "
                  "CONFIRMED")
    if project["inspection_status"] != "NOT_SCHEDULED":
        raise_err(ERR_INVALID_STATE,
                  "Project inspection already scheduled or completed")

    # Priority 6: temporal — inverted window
    start_dt = db.parse_iso(win_start)
    end_dt = db.parse_iso(win_end)
    if not (start_dt < end_dt):
        raise_err(ERR_INVALID_WINDOW,
                  "inspection_window_start must be strictly before "
                  "inspection_window_end")

    # Priority 7: (hall, booth_number) unique per edition
    for b in db.booth_assignments.values():
        bp = db.projects.get(b["project_id"])
        if (bp is not None
                and bp["fair_edition_id"] == project["fair_edition_id"]
                and b["hall"] == hall
                and b["booth_number"] == booth_number):
            raise_err(ERR_BOOTH_TAKEN,
                      f"Booth ({hall}, {booth_number}) already occupied in "
                      f"this edition")

    now = db.now_display_iso()
    b = {
        "id": db.new_id(),
        "project_id": pid,
        "hall": hall,
        "booth_number": booth_number,
        "inspection_window_start": win_start,
        "inspection_window_end": win_end,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.booth_assignments[b["id"]] = b

    project["inspection_status"] = "SCHEDULED"
    _touch(project)

    return success_object(booth_assignment_out(b), 201)


@bp.route("/science-fair/booth-assignments", methods=["GET"])
def list_booth_assignments():
    require_roles("FairDirector", "OperationsLead", "SafetyInspector",
                  "Mentor")
    limit, offset = parse_pagination()
    items = list(db.booth_assignments.values())
    pid = request.args.get("project_id")
    if pid:
        items = [b for b in items if b["project_id"] == pid]
    hall = request.args.get("hall")
    if hall:
        items = [b for b in items if b["hall"] == hall]
    data, total = paginate(items, booth_assignment_out, limit, offset)
    return success_list(data, limit, offset, total)


@bp.route("/science-fair/booth-assignments/<bid>", methods=["GET"])
def get_booth_assignment(bid):
    require_roles("FairDirector", "OperationsLead", "SafetyInspector",
                  "Mentor")
    b = db.booth_assignments.get(bid)
    if b is None:
        raise_err(ERR_NOT_FOUND, f"Booth assignment not found: {bid}")
    return success_object(booth_assignment_out(b))


@bp.route("/science-fair/projects/<pid>/inspection-result", methods=["POST"])
def record_inspection_result(pid):
    body = V.get_json_body()
    V.require_fields(body, ["result"])
    result = V.req_enum(body, "result", _VALID_RESULT)

    require_roles("SafetyInspector")

    project = db.projects.get(pid)
    if project is None:
        raise_err(ERR_NOT_FOUND, f"Project not found: {pid}")

    if project["inspection_status"] in ("PASSED", "FAILED"):
        raise_err(ERR_ALREADY_TERMINAL,
                  f"Inspection is {project['inspection_status']} (terminal)")
    if project["inspection_status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE,
                  "Inspection result requires inspection_status SCHEDULED")

    # Find the booth assignment to get the window
    booth = None
    for b in db.booth_assignments.values():
        if b["project_id"] == pid:
            booth = b
            break
    if booth is None:
        raise_err(ERR_INVALID_STATE,
                  "No booth assignment / inspection window for project")

    # Priority 6: logical clock within window (inclusive)
    now_dt = db.parse_iso(db.clock_now_iso())
    if not (db.parse_iso(booth["inspection_window_start"]) <= now_dt
            <= db.parse_iso(booth["inspection_window_end"])):
        raise_err(ERR_OUTSIDE_WINDOW,
                  "Inspection result recorded outside the scheduled window")

    if result == "PASS":
        project["inspection_status"] = "PASSED"
    else:
        project["inspection_status"] = "FAILED"
        project["registration_status"] = "WITHDRAWN"
    _touch(project)

    return success_object(project_out(project))
