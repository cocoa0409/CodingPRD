"""Fair entries, pens, and stall assignments (PRD 3.8)."""

from flask import Blueprint, request

import db
import response
from middleware import (authenticate, resolve_caller, must_find,
                        require_member_ownership, new_common_fields, touch)
from validation import (get_body, as_str, as_enum, as_int_range,
                        pagination_params, paginate, sort_by_creation, present)
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_PEN_CAPACITY_EXCEEDED, ERR_OWNERSHIP_PERIOD_SHORT,
                    ERR_REFERENTIAL_INTEGRITY)
from services import calc
from services.serialize import fair_entry_view, stall_assignment_view, pen_view

pens_bp = Blueprint("pens", __name__)
bp = Blueprint("fair_entries", __name__)
stalls_bp = Blueprint("stall_assignments", __name__)

ALL_ROLES = ["ProgramAdmin", "Volunteer", "Member"]
FAIR_LEVELS = ("COUNTY", "STATE")


# --------------------------------------------------------------------------
# Pens
# --------------------------------------------------------------------------
@pens_bp.post("/pens")
def create_pen():
    role, user_id = authenticate(["ProgramAdmin"])
    resolve_caller(role, user_id)
    body = get_body()
    label = as_str(body, "label")
    animal_capacity = as_int_range(body, "animal_capacity", lo=0)
    # Pen labels are unique (PRD 3.8).
    for existing in db.table("pens").values():
        if existing["label"] == label:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "A pen labelled '%s' already exists" % label)
    rec = new_common_fields()
    rec.update({"label": label, "animal_capacity": animal_capacity})
    db.table("pens")[rec["id"]] = rec
    return response.success(pen_view(rec), status=201)


@pens_bp.get("/pens/<pid>")
def get_pen(pid):
    role, user_id = authenticate(["ProgramAdmin", "Volunteer"])
    rec = must_find("pens", pid, "Pen")
    resolve_caller(role, user_id)
    return response.success(pen_view(rec))


@pens_bp.get("/pens/<pid>/stall-assignments")
def list_pen_stall_assignments(pid):
    role, user_id = authenticate(["ProgramAdmin", "Volunteer"])
    pen = must_find("pens", pid, "Pen")
    resolve_caller(role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation(
        [s for s in db.table("stall_assignments").values() if s["pen_id"] == pen["id"]])
    page, meta = paginate(items, limit, offset)
    return response.success([stall_assignment_view(s) for s in page],
                            response_type="array", pagination=meta)


# --------------------------------------------------------------------------
# Fair entries
# --------------------------------------------------------------------------
@bp.post("/fair-entries")
def create_fair_entry():
    role, user_id = authenticate(["Member"])
    body = get_body()
    # Priority 3: referenced identifiers exist, left-to-right (member_id, project_id).
    member = None
    project = None
    if isinstance(body.get("member_id"), str):
        member = must_find("members", body["member_id"], "Member")
    if isinstance(body.get("project_id"), str):
        project = must_find("projects", body["project_id"], "Project")
    resolve_caller(role, user_id)
    # Priority 4: a member enters their own membership into a fair.
    if isinstance(body.get("member_id"), str):
        require_member_ownership(user_id, body["member_id"])
    # Priority 13: referential integrity -- the project must belong to the
    # entering member.
    if member is not None and project is not None:
        if project["member_id"] != member["id"]:
            raise ApiError(ERR_REFERENTIAL_INTEGRITY, 422,
                           "The fair entry's project must belong to the entry's member")
    # Priority 14: request shape.
    member_id = present(body, "member_id")
    if not isinstance(member_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'member_id': must be a string")
    project_id = present(body, "project_id")
    if not isinstance(project_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'project_id': must be a string")
    if member is None:
        member = must_find("members", member_id, "Member")
    if project is None:
        project = must_find("projects", project_id, "Project")
    fair_level = as_enum(body, "fair_level", FAIR_LEVELS)
    rec = new_common_fields()
    rec.update({
        "member_id": member["id"],
        "project_id": project["id"],
        "fair_level": fair_level,
        "status": "ENTERED",
        # Computed at creation against the fixed 2026-08-01T00:00:00Z deadline;
        # None when the project has no VERIFIED animal tag.
        "ownership_days_at_entry": calc.ownership_days_at_entry(project["id"]),
    })
    db.table("fair_entries")[rec["id"]] = rec
    return response.success(fair_entry_view(rec), status=201)


@bp.get("/fair-entries")
def list_fair_entries():
    role, user_id = authenticate(ALL_ROLES)
    resolve_caller(role, user_id)
    limit, offset = pagination_params()
    items = list(db.table("fair_entries").values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [e for e in items if e["project_id"] == project_id]
    member_id = request.args.get("member_id")
    if member_id is not None:
        items = [e for e in items if e["member_id"] == member_id]
    items = sort_by_creation(items)
    page, meta = paginate(items, limit, offset)
    return response.success([fair_entry_view(e) for e in page],
                            response_type="array", pagination=meta)


@bp.get("/fair-entries/<eid>")
def get_fair_entry(eid):
    role, user_id = authenticate(ALL_ROLES)
    rec = must_find("fair_entries", eid, "FairEntry")
    resolve_caller(role, user_id)
    return response.success(fair_entry_view(rec))


@bp.post("/fair-entries/<eid>/confirm")
def confirm_fair_entry(eid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("fair_entries", eid, "FairEntry")
    resolve_caller(role, user_id)
    # Priority 5: ENTERED -> CONFIRMED requires the member's posture ELIGIBLE.
    if rec["status"] != "ENTERED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Fair entry status must be ENTERED to confirm")
    member = db.table("members").get(rec["member_id"])
    if member is None or member["eligibility_posture"] != "ELIGIBLE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Confirming a fair entry requires eligibility_posture ELIGIBLE")
    # Priority 11: ownership period -- at least 60 days for BEEF, at least 30
    # for SHEEP or SWINE; exactly the required number qualifies.
    project = db.table("projects").get(rec["project_id"])
    if project is not None and project["project_type"] in calc.LIVESTOCK_TYPES:
        required = calc.species_min_ownership_days(project["project_type"])
        days = rec["ownership_days_at_entry"]
        if days is None or days < required:
            raise ApiError(ERR_OWNERSHIP_PERIOD_SHORT, 422,
                           "Animal ownership days at the fair deadline fall below the species minimum (%d)"
                           % required)
    rec["status"] = "CONFIRMED"
    touch(rec)
    return response.success(fair_entry_view(rec))


@bp.post("/fair-entries/<eid>/mark-exhibited")
def mark_fair_entry_exhibited(eid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("fair_entries", eid, "FairEntry")
    resolve_caller(role, user_id)
    if rec["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Fair entry status must be CONFIRMED to mark exhibited")
    has_assigned = any(s["fair_entry_id"] == rec["id"] and s["status"] == "ASSIGNED"
                       for s in db.table("stall_assignments").values())
    if not has_assigned:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Marking exhibited requires a stall assignment in ASSIGNED status")
    rec["status"] = "EXHIBITED"
    touch(rec)
    return response.success(fair_entry_view(rec))


def _release_entry_stalls(entry_id):
    """Release any ASSIGNED stall assignment for the entry, freeing pen
    capacity; each released assignment advances its own version (PRD 2.4)."""
    for stall in db.table("stall_assignments").values():
        if stall["fair_entry_id"] == entry_id and stall["status"] == "ASSIGNED":
            stall["status"] = "RELEASED"
            touch(stall)


@bp.post("/fair-entries/<eid>/scratch")
def scratch_fair_entry(eid):
    role, user_id = authenticate(["Member", "Volunteer"])
    rec = must_find("fair_entries", eid, "FairEntry")
    resolve_caller(role, user_id)
    # Priority 4: a member may scratch only their own entry.
    if role == "Member":
        require_member_ownership(user_id, rec["member_id"])
    # Priority 5: a member may scratch their own entry while it is ENTERED,
    # and a volunteer may scratch a CONFIRMED entry (PRD 3.8).
    if role == "Member":
        if rec["status"] != "ENTERED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "A member may scratch their own entry only while it is ENTERED")
    else:
        if rec["status"] != "CONFIRMED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "A volunteer may scratch an entry only while it is CONFIRMED")
    rec["status"] = "SCRATCHED"
    touch(rec)
    _release_entry_stalls(rec["id"])
    return response.success(fair_entry_view(rec))


@bp.get("/fair-entries/<eid>/stall-assignments")
def list_fair_entry_stall_assignments(eid):
    role, user_id = authenticate(ALL_ROLES)
    entry = must_find("fair_entries", eid, "FairEntry")
    resolve_caller(role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation(
        [s for s in db.table("stall_assignments").values()
         if s["fair_entry_id"] == entry["id"]])
    page, meta = paginate(items, limit, offset)
    return response.success([stall_assignment_view(s) for s in page],
                            response_type="array", pagination=meta)


# --------------------------------------------------------------------------
# Stall assignments
# --------------------------------------------------------------------------
@stalls_bp.post("/stall-assignments")
def create_stall_assignment():
    role, user_id = authenticate(["Volunteer"])
    body = get_body()
    # Priority 3: referenced identifiers exist, left-to-right (fair_entry_id, pen_id).
    entry = None
    pen = None
    if isinstance(body.get("fair_entry_id"), str):
        entry = must_find("fair_entries", body["fair_entry_id"], "FairEntry")
    if isinstance(body.get("pen_id"), str):
        pen = must_find("pens", body["pen_id"], "Pen")
    resolve_caller(role, user_id)
    # Priority 5: once an entry is confirmed, fairground logistics take over
    # (PRD 3.8) -- stall assignment requires a CONFIRMED entry.
    if entry is not None and entry["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "A stall can only be assigned to a CONFIRMED fair entry")
    # Priority 9: pen capacity -- an aggregate count, not an interval rule.
    if pen is not None:
        assigned = sum(1 for s in db.table("stall_assignments").values()
                       if s["pen_id"] == pen["id"] and s["status"] == "ASSIGNED")
        if assigned + 1 > pen["animal_capacity"]:
            raise ApiError(ERR_PEN_CAPACITY_EXCEEDED, 422,
                           "Stall assignment would exceed the pen's animal_capacity")
    # Priority 14: request shape.
    fair_entry_id = present(body, "fair_entry_id")
    if not isinstance(fair_entry_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'fair_entry_id': must be a string")
    pen_id = present(body, "pen_id")
    if not isinstance(pen_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'pen_id': must be a string")
    if entry is None:
        entry = must_find("fair_entries", fair_entry_id, "FairEntry")
    if pen is None:
        pen = must_find("pens", pen_id, "Pen")
    rec = new_common_fields()
    rec.update({
        "fair_entry_id": entry["id"],
        "pen_id": pen["id"],
        "status": "ASSIGNED",
    })
    db.table("stall_assignments")[rec["id"]] = rec
    return response.success(stall_assignment_view(rec), status=201)


@stalls_bp.post("/stall-assignments/<sid>/release")
def release_stall_assignment(sid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("stall_assignments", sid, "StallAssignment")
    resolve_caller(role, user_id)
    if rec["status"] != "ASSIGNED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Stall assignment status must be ASSIGNED to release")
    rec["status"] = "RELEASED"
    touch(rec)
    return response.success(stall_assignment_view(rec))
