"""Crew endpoints (PRD §3.3, §2.8)."""

from datetime import timedelta

from flask import Blueprint, request

from db import db, now_iso, _parse_iso
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_MANNING_SHORTFALL,
    ERR_CREW_REST_CONFLICT,
)
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services.calculations import touch, crew_manning_compliance
from services.serializers import serialize_crew_member, serialize_crew_assignment
from services.sailing_ops import release_assignment

bp = Blueprint("crew", __name__)

REST_MINUTES = 480


@bp.post("/ferry/crew-members")
def create_crew_member():
    require_roles("CrewPlanner")
    payload = request.get_json(silent=True) or {}
    ts = now_iso()
    member = {
        "id": db.new_id(),
        "full_name": payload.get("full_name"),
        "credential_class": payload.get("credential_class"),
        "status": "AVAILABLE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.crew_members[member["id"]] = member
    return success_object(serialize_crew_member(member), status=201)


@bp.get("/ferry/crew-members/<member_id>")
def get_crew_member(member_id):
    require_roles("SchedulerAdmin", "TerminalAgent", "CrewPlanner")
    member = db.crew_members.get(member_id)
    if member is None:
        raise_error(ERR_NOT_FOUND, "Crew member not found")
    return success_object(serialize_crew_member(member))


@bp.get("/ferry/crew-members/<member_id>/crew-assignments")
def list_member_assignments(member_id):
    require_roles("SchedulerAdmin", "CrewPlanner")
    member = db.crew_members.get(member_id)
    if member is None:
        raise_error(ERR_NOT_FOUND, "Crew member not found")
    status = request.args.get("status")
    items = [a for a in db.crew_assignments.values()
             if a["crew_member_id"] == member_id
             and (status is None or a["status"] == status)]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    limit, offset = parse_pagination(request.args)
    page, meta = paginate(items, limit, offset)
    return success_list([serialize_crew_assignment(a) for a in page], meta)


@bp.post("/ferry/crew-members/<member_id>/set-off-duty")
def set_off_duty(member_id):
    require_roles("CrewPlanner")
    member = db.crew_members.get(member_id)
    if member is None:
        raise_error(ERR_NOT_FOUND, "Crew member not found")
    # AVAILABLE -> OFF_DUTY only
    if member["status"] != "AVAILABLE":
        raise_error(ERR_INVALID_STATE,
                    f"Cannot set off duty a crew member in status {member['status']}")
    member["status"] = "OFF_DUTY"
    touch(member)
    return success_object(serialize_crew_member(member))


@bp.post("/ferry/crew-members/<member_id>/set-available")
def set_available(member_id):
    require_roles("CrewPlanner")
    member = db.crew_members.get(member_id)
    if member is None:
        raise_error(ERR_NOT_FOUND, "Crew member not found")
    # OFF_DUTY -> AVAILABLE only
    if member["status"] != "OFF_DUTY":
        raise_error(ERR_INVALID_STATE,
                    f"Cannot set available a crew member in status {member['status']}")
    member["status"] = "AVAILABLE"
    touch(member)
    return success_object(serialize_crew_member(member))


@bp.post("/ferry/sailings/<sailing_id>/crew-assignments")
def create_crew_assignment(sailing_id):
    require_roles("CrewPlanner")

    # Priority 3: path id (sailing) resolved before body FK (crew member) — §2.10
    sailing = db.sailings.get(sailing_id)
    if sailing is None:
        raise_error(ERR_NOT_FOUND, "Sailing not found")

    payload = request.get_json(silent=True) or {}
    member = db.crew_members.get(payload.get("crew_member_id"))
    if member is None:
        raise_error(ERR_NOT_FOUND, "Crew member not found")

    # State machine: AVAILABLE -> ASSIGNED on assignment. A member already
    # ASSIGNED may receive further assignments (the 480-minute rest/overlap
    # rule below exists precisely to police multiple live assignments per
    # member, PRD §3.3); only OFF_DUTY members are unavailable for assignment.
    if member["status"] == "OFF_DUTY":
        raise_error(ERR_INVALID_STATE,
                    "Crew member is OFF_DUTY and cannot be assigned")

    shift_start = _parse_iso(payload.get("shift_start"))
    shift_end = _parse_iso(payload.get("shift_end"))
    if not (shift_start < shift_end):
        raise_error(ERR_CREW_REST_CONFLICT,
                    "shift_end must be strictly later than shift_start")

    # Priority 10: crew temporal overlap — no two ASSIGNED assignments for the
    # same member with overlapping half-open [shift_start, shift_end) intervals
    # or less than 480 minutes rest between them.
    rest = timedelta(minutes=REST_MINUTES)
    for a in db.crew_assignments.values():
        if a["crew_member_id"] != member["id"] or a["status"] != "ASSIGNED":
            continue
        a_start = _parse_iso(a["shift_start"])
        a_end = _parse_iso(a["shift_end"])
        overlap = shift_start < a_end and a_start < shift_end
        # Rest rule: gap between intervals (in either direction) must be >= 480 min.
        gap_ok = (shift_start >= a_end + rest) or (a_start >= shift_end + rest)
        if overlap or not gap_ok:
            raise_error(ERR_CREW_REST_CONFLICT,
                        "Crew assignment overlaps an existing assignment or "
                        "violates the 480-minute rest rule")

    ts = now_iso()
    assignment = {
        "id": db.new_id(),
        "sailing_id": sailing_id,
        "crew_member_id": member["id"],
        "shift_start": payload.get("shift_start"),
        "shift_end": payload.get("shift_end"),
        "status": "ASSIGNED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.crew_assignments[assignment["id"]] = assignment

    # Side effects: member AVAILABLE -> ASSIGNED (first live assignment);
    # manning_ok recomputed
    if member["status"] == "AVAILABLE":
        member["status"] = "ASSIGNED"
        touch(member)
    sailing["manning_ok"] = crew_manning_compliance(sailing)
    touch(sailing)
    return success_object(serialize_crew_assignment(assignment), status=201)


@bp.post("/ferry/crew-assignments/<assignment_id>/release")
def release_crew_assignment(assignment_id):
    require_roles("CrewPlanner")
    assignment = db.crew_assignments.get(assignment_id)
    if assignment is None:
        raise_error(ERR_NOT_FOUND, "Crew assignment not found")

    if assignment["status"] != "ASSIGNED":
        raise_error(ERR_INVALID_STATE,
                    f"Cannot release a crew assignment in status {assignment['status']}")

    sailing = db.sailings[assignment["sailing_id"]]

    # Release permitted only while the sailing has not departed (§3.3)
    if sailing["status"] == "DEPARTED":
        raise_error(ERR_INVALID_STATE,
                    "Cannot release a crew assignment after departure")

    # Priority 8: releasing must not break manning for a sailing still relying
    # on it (open-booking already passed the gate).
    if sailing["status"] in ("OPEN_FOR_BOOKING", "BOOKING_CLOSED", "BOARDING"):
        # Hypothetically remove this assignment and re-check the table.
        assignment["status"] = "RELEASED"
        still_ok = crew_manning_compliance(sailing)
        assignment["status"] = "ASSIGNED"
        if not still_ok:
            raise_error(ERR_MANNING_SHORTFALL,
                        "Releasing this assignment would break the manning table")

    release_assignment(assignment)
    sailing["manning_ok"] = crew_manning_compliance(sailing)
    touch(sailing)
    return success_object(serialize_crew_assignment(assignment))


@bp.get("/ferry/crew-assignments/<assignment_id>")
def get_crew_assignment(assignment_id):
    require_roles("SchedulerAdmin", "CrewPlanner")
    assignment = db.crew_assignments.get(assignment_id)
    if assignment is None:
        raise_error(ERR_NOT_FOUND, "Crew assignment not found")
    return success_object(serialize_crew_assignment(assignment))
