"""PanelAssignment rostering and attendance bookkeeping (PRD §3.5)."""
import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_INVALID_SESSION_STATE, ERR_PANELIST_NOT_QUALIFIED,
    ERR_PANELIST_DOUBLE_BOOKED, ERR_SESSION_FULL,
    ERR_INVALID_ASSIGNMENT_STATE,
)
from flask import Blueprint, request
from response import respond, respond_list
from services import ser_assignment, assignments_of_session, suspend_panelist
from util import body, paginate, req_str, sort_created, touch

bp = Blueprint("assignments", __name__)


def get_assignment(assignment_id):
    a = db.store["assignments"].get(assignment_id)
    if a is None:
        raise_err(ERR_NOT_FOUND, f"PanelAssignment {assignment_id} not found")
    return a


@bp.route("/panel-assignments", methods=["POST"])
@require_roles("PanelCoordinator")
def create_assignment():
    b = body()
    session_id = req_str(b, "session_id")
    panelist_id = req_str(b, "panelist_id")
    session = db.store["sessions"].get(session_id)
    if session is None:
        raise_err(ERR_NOT_FOUND, f"EvaluationSession {session_id} not found")
    panelist = db.store["panelists"].get(panelist_id)
    if panelist is None:
        raise_err(ERR_NOT_FOUND, f"Panelist {panelist_id} not found")
    if session["status"] not in ("PLANNED", "OPEN"):
        raise_err(ERR_INVALID_SESSION_STATE,
                  "assignments require the session to be PLANNED or OPEN")
    if panelist["status"] != "QUALIFIED":
        raise_err(ERR_PANELIST_NOT_QUALIFIED,
                  "panelist must be QUALIFIED to be assigned")
    # Roster headroom (§2.6 rung 7 precedes the double-booking rung 9).
    active = sum(1 for a in assignments_of_session(session_id)
                 if a["status"] in ("ASSIGNED", "SUBMITTED"))
    if active >= session["required_panelist_count"] + 2:
        raise_err(ERR_SESSION_FULL,
                  "session active assignment count is already "
                  "required_panelist_count + 2")
    # Half-open [start, end) intersection on OTHER sessions; back-to-back
    # is legal (PRD §3.5).
    s1, e1 = session["scheduled_start_utc"], session["scheduled_end_utc"]
    for other in db.store["assignments"].values():
        if other["panelist_id"] != panelist_id:
            continue
        if other["status"] not in ("ASSIGNED", "SUBMITTED"):
            continue
        if other["session_id"] == session_id:
            continue
        osess = db.store["sessions"][other["session_id"]]
        s2, e2 = osess["scheduled_start_utc"], osess["scheduled_end_utc"]
        if s1 < e2 and s2 < e1:
            raise_err(ERR_PANELIST_DOUBLE_BOOKED,
                      "panelist already holds an assignment on a session "
                      "whose window strictly intersects this one")
    # The same panelist may not hold two assignments on the same session.
    for other in assignments_of_session(session_id):
        if other["panelist_id"] == panelist_id:
            raise_err(ERR_INVALID_REQUEST,
                      "panelist already holds an assignment on this session")
    now = clock.now()
    assignment = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "session_id": session_id,
        "panelist_id": panelist_id,
        "status": "ASSIGNED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["assignments"][assignment["id"]] = assignment
    return respond(ser_assignment(assignment), 201)


@bp.route("/panel-assignments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_assignments():
    items = sort_created(db.store["assignments"].values())
    for field in ("session_id", "panelist_id", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [a for a in items if a[field] == v]
    page, pagination = paginate(items)
    return respond_list([ser_assignment(a) for a in page], pagination)


@bp.route("/panel-assignments/<assignment_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_assignment(assignment_id):
    return respond(ser_assignment(get_assignment(assignment_id)), 200)


@bp.route("/panel-assignments/<assignment_id>/mark-no-show", methods=["POST"])
@require_roles("PanelCoordinator")
def mark_no_show(assignment_id):
    assignment = get_assignment(assignment_id)
    if assignment["status"] != "ASSIGNED":
        raise_err(ERR_INVALID_ASSIGNMENT_STATE,
                  "mark-no-show requires status ASSIGNED")
    session = db.store["sessions"][assignment["session_id"]]
    if session["status"] != "OPEN":
        raise_err(ERR_INVALID_SESSION_STATE,
                  "mark-no-show requires the session to be OPEN")
    assignment["status"] = "NO_SHOW"
    touch(assignment)
    panelist = db.store["panelists"][assignment["panelist_id"]]
    panelist["consecutive_no_shows"] += 1
    touch(panelist)
    if (panelist["consecutive_no_shows"] >= 3
            and panelist["status"] == "QUALIFIED"):
        suspend_panelist(panelist)
    return respond(ser_assignment(assignment), 200)


@bp.route("/panel-assignments/<assignment_id>/excuse", methods=["POST"])
@require_roles("PanelCoordinator")
def excuse(assignment_id):
    assignment = get_assignment(assignment_id)
    if assignment["status"] != "ASSIGNED":
        raise_err(ERR_INVALID_ASSIGNMENT_STATE,
                  "excuse requires status ASSIGNED")
    assignment["status"] = "EXCUSED"
    touch(assignment)
    return respond(ser_assignment(assignment), 200)
