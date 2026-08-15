"""RotationAssignment endpoints: create, list, get, complete, mark-missed, swap."""

from datetime import datetime, timedelta, timezone
from flask import request, Blueprint

import db
import util
from util import D, is_multiple_quarter
from middleware import auth_context
from errors import raise_err
from response import success_object, success_list
from services import calculations as calc

bp = Blueprint("rotation", __name__)

ALL_ROLES = ["ProgramCoordinator", "Volunteer", "Specialist"]
PC = ["ProgramCoordinator"]

CONSECUTIVE_WEEK_LIMIT = 2


def get_assignment_or_404(assignment_id):
    a = db.rotation_assignments.get(assignment_id)
    if a is None:
        raise_err("ERR_NOT_FOUND", "RotationAssignment not found")
    return a


def _week_end_instant(week_start_date):
    """The instant exactly 7 days after week_start 00:00:00 UTC."""
    d = util.parse_date(week_start_date)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(days=7)


def _check_bed_week_conflict(bed_code, week_start, week_end, exclude_id=None):
    """Overlap rule C: closed day-granularity week ranges on same bed."""
    for a in db.rotation_assignments.values():
        if a["bed_code"] != bed_code:
            continue
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        if a["status"] not in ("ASSIGNED", "COMPLETED"):
            continue
        ex_start = util.parse_date(a["week_start"])
        ex_end = util.parse_date(a["week_end"])
        if week_start <= ex_end and ex_start <= week_end:
            raise_err("ERR_BED_WEEK_CONFLICT",
                      "Another ASSIGNED/COMPLETED assignment occupies this bed in an overlapping week")


def _check_consecutive_weeks(volunteer_id, bed_code, week_start):
    """Chain of unbroken Monday-to-Monday weeks ending immediately before week_start."""
    weeks = [a for a in db.rotation_assignments.values()
             if a["volunteer_id"] == volunteer_id
             and a["bed_code"] == bed_code
             and a["status"] in ("ASSIGNED", "COMPLETED")]
    week_starts = {util.parse_date(a["week_start"]) for a in weeks}
    consecutive = 0
    cursor = week_start - timedelta(days=7)
    while cursor in week_starts:
        consecutive += 1
        cursor -= timedelta(days=7)
    if consecutive >= CONSECUTIVE_WEEK_LIMIT:
        raise_err("ERR_CONSECUTIVE_WEEK_LIMIT",
                  "Volunteer already holds 2 consecutive weeks on this bed")


def _derive_cycle(week_start):
    """The unique OPEN cycle whose [start_date, end_date] contains week_start."""
    matches = [c for c in db.program_cycles.values()
               if c["status"] == "OPEN"
               and util.parse_date(c["start_date"]) <= week_start <= util.parse_date(c["end_date"])]
    if not matches:
        raise_err("ERR_NO_OPEN_CYCLE", "No OPEN cycle contains the requested week_start")
    matches.sort(key=lambda c: c["created_at"])
    return matches[0]


@bp.route("/rotation-assignments", methods=["POST"])
def create_assignment():
    auth_context(PC)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    for f in ("bed_code", "volunteer_id", "week_start"):
        if f not in body:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")
    if not isinstance(body["bed_code"], str) or not body["bed_code"]:
        raise_err("ERR_INVALID_REQUEST", "bed_code must be a non-empty string")
    if not isinstance(body["volunteer_id"], str):
        raise_err("ERR_INVALID_REQUEST", "volunteer_id must be a string")
    if not isinstance(body["week_start"], str) or not util.is_iso_date(body["week_start"]):
        raise_err("ERR_INVALID_REQUEST", "week_start must be an ISO 8601 date")
    week_start = util.parse_date(body["week_start"])
    if week_start.weekday() != 0:
        raise_err("ERR_INVALID_FIELD_VALUE", "week_start must be a Monday")

    vol = db.volunteers.get(body["volunteer_id"])
    if vol is None:
        raise_err("ERR_NOT_FOUND", "volunteer_id does not resolve")
    if vol["status"] != "ACTIVE":
        raise_err("ERR_VOLUNTEER_NOT_ACTIVE", "Rotation assignment requires an ACTIVE volunteer")

    week_end = week_start + timedelta(days=6)
    cycle = _derive_cycle(week_start)
    _check_bed_week_conflict(body["bed_code"], week_start, week_end)
    _check_consecutive_weeks(vol["id"], body["bed_code"], week_start)

    assignment = util.new_resource({
        "bed_code": body["bed_code"],
        "volunteer_id": vol["id"],
        "cycle_id": cycle["id"],
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "status": "ASSIGNED",
        "actual_hours": None,
        "swapped_to_id": None,
    })
    db.rotation_assignments[assignment["id"]] = assignment
    return success_object(assignment, 201)


@bp.route("/rotation-assignments", methods=["GET"])
def list_assignments():
    auth_context(ALL_ROLES)
    items = list(db.rotation_assignments.values())
    for param in ("bed_code", "volunteer_id", "cycle_id", "status", "swapped_to_id"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a.get(param) == v]
    items = util.sort_created(items)
    limit, offset = util.paginate(items, request.args)
    return success_list(items[offset:offset + limit], len(items), limit, offset)


@bp.route("/rotation-assignments/<assignmentId>", methods=["GET"])
def get_assignment(assignmentId):
    auth_context(ALL_ROLES)
    return success_object(get_assignment_or_404(assignmentId))


@bp.route("/rotation-assignments/<assignmentId>/complete", methods=["POST"])
def complete_assignment(assignmentId):
    auth_context(PC)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if "actual_hours" not in body:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: actual_hours")
    ah = body["actual_hours"]
    if not isinstance(ah, (int, float)) or isinstance(ah, bool):
        raise_err("ERR_INVALID_REQUEST", "actual_hours must be a number")
    ahd = D(ah)
    if ahd < D("0.5") or ahd > D("8.0") or not is_multiple_quarter(ahd):
        raise_err("ERR_INVALID_FIELD_VALUE", "actual_hours must be 0.5..8.0 in steps of 0.25")

    assignment = get_assignment_or_404(assignmentId)
    if assignment["status"] != "ASSIGNED":
        raise_err("ERR_ASSIGNMENT_NOT_ASSIGNED", "Complete requires an ASSIGNED assignment")
    clock = util.logical_clock()
    if clock < _week_end_instant(assignment["week_start"]):
        raise_err("ERR_WEEK_NOT_ENDED", "The rotation week has not ended yet")

    assignment["status"] = "COMPLETED"
    assignment["actual_hours"] = float(ahd)
    util.touch(assignment)
    entry = util.new_resource({
        "volunteer_id": assignment["volunteer_id"],
        "cycle_id": assignment["cycle_id"],
        "entry_kind": "SERVICE",
        "activity_type": "GARDEN",
        "provider": None,
        "title": None,
        "activity_date": assignment["week_end"],
        "hours": float(ahd),
        "status": "PENDING",
        "source_type": "ROTATION",
        "source_id": assignment["id"],
        "note": None,
        "decided_at": None,
    })
    db.credit_entries[entry["id"]] = entry
    return success_object(assignment)


@bp.route("/rotation-assignments/<assignmentId>/mark-missed", methods=["POST"])
def mark_missed(assignmentId):
    auth_context(PC)
    assignment = get_assignment_or_404(assignmentId)
    if assignment["status"] != "ASSIGNED":
        raise_err("ERR_ASSIGNMENT_NOT_ASSIGNED", "Mark-missed requires an ASSIGNED assignment")
    clock = util.logical_clock()
    if clock < _week_end_instant(assignment["week_start"]):
        raise_err("ERR_WEEK_NOT_ENDED", "The rotation week has not ended yet")
    assignment["status"] = "MISSED"
    util.touch(assignment)
    return success_object(assignment)


@bp.route("/rotation-assignments/<assignmentId>/swap", methods=["POST"])
def swap_assignment(assignmentId):
    auth_context(PC)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if "new_volunteer_id" not in body:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: new_volunteer_id")
    if not isinstance(body["new_volunteer_id"], str):
        raise_err("ERR_INVALID_REQUEST", "new_volunteer_id must be a string")

    assignment = get_assignment_or_404(assignmentId)
    if assignment["status"] != "ASSIGNED":
        raise_err("ERR_ASSIGNMENT_NOT_ASSIGNED", "Swap requires an ASSIGNED assignment")
    new_vol = db.volunteers.get(body["new_volunteer_id"])
    if new_vol is None:
        raise_err("ERR_NOT_FOUND", "new_volunteer_id does not resolve")
    clock = util.logical_clock()
    if clock >= _week_end_instant(assignment["week_start"]):
        raise_err("ERR_SWAP_WINDOW_CLOSED", "Swap window closed: the rotation week has ended")
    if new_vol["status"] != "ACTIVE":
        raise_err("ERR_VOLUNTEER_NOT_ACTIVE", "new_volunteer_id must reference an ACTIVE volunteer")

    week_start = util.parse_date(assignment["week_start"])
    week_end = util.parse_date(assignment["week_end"])
    # replacement must pass creation rules (SWAPPED originals do not block;
    # exclude the original assignment id explicitly for safety)
    _check_bed_week_conflict(assignment["bed_code"], week_start, week_end, exclude_id=assignment["id"])
    _check_consecutive_weeks(new_vol["id"], assignment["bed_code"], week_start)

    replacement = util.new_resource({
        "bed_code": assignment["bed_code"],
        "volunteer_id": new_vol["id"],
        "cycle_id": assignment["cycle_id"],
        "week_start": assignment["week_start"],
        "week_end": assignment["week_end"],
        "status": "ASSIGNED",
        "actual_hours": None,
        "swapped_to_id": None,
    })
    db.rotation_assignments[replacement["id"]] = replacement
    assignment["status"] = "SWAPPED"
    assignment["swapped_to_id"] = replacement["id"]
    util.touch(assignment)
    return success_object(replacement)
