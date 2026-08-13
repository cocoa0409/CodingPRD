"""Staff assignments under a cruise: create, list, confirm, release."""
from flask import Blueprint, request

import clock
import db
from errors import ApiError, err_invalid_request, err_invalid_state
from response import ok
from serializers import serialize as _sz, serialize_list as _szl
from services import core as svc
from util import require_auth, get_json, paginate, get_or_404, touch, check_enum

bp = Blueprint("staff_assignments", __name__)

OM = ["OperationsManager"]
READ = ["OperationsManager", "Captain", "GalleyManager"]
ROLE_CODES = ["SERVER", "BARTENDER", "GALLEY", "ENTERTAINER", "DECKHAND"]
ASSIGNMENT_STATUSES = ["ASSIGNED", "CONFIRMED", "RELEASED"]


@bp.post("/cruises/<cid>/staff-assignments")
def create_assignment(cid):
    require_auth(OM)
    cruise = get_or_404(db.cruises, cid, "cruise", "Cruise not found")
    body = get_json(required_fields=["staff_member_id", "assigned_role"])
    staff_id = body["staff_member_id"]
    if not isinstance(staff_id, str):
        raise err_invalid_request("staff_member_id must be a string")
    role = check_enum(body, "assigned_role", ROLE_CODES)
    member = db.staff_members.get(staff_id)
    if member is None:
        from errors import NOT_FOUND_IDS, err_not_found
        raise err_not_found(NOT_FOUND_IDS["staff_member"], "Staff member not found")
    now_z = clock.to_z(clock.now())
    assignment = {
        "id": db.new_id(), "created_at": now_z, "updated_at": now_z, "version": 1,
        "cruise_id": cruise["id"],
        "staff_member_id": member["id"],
        "assigned_role": role,
        "status": "ASSIGNED",
    }
    db.insert(db.assignments, assignment)
    return ok(_sz("assignment", assignment), status=201)


@bp.get("/cruises/<cid>/staff-assignments")
def list_assignments(cid):
    require_auth(READ)
    cruise = get_or_404(db.cruises, cid, "cruise", "Cruise not found")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in ASSIGNMENT_STATUSES:
        raise err_invalid_request("Invalid value for status")
    items = [a for a in db.assignments.values() if a["cruise_id"] == cruise["id"]]
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    items.sort(key=lambda a: a["created_at"])
    page, meta = paginate(items)
    return ok(_szl("assignment", page), pagination=meta)


def _load_assignment(cid, aid):
    cruise = get_or_404(db.cruises, cid, "cruise", "Cruise not found")
    assignment = db.assignments.get(aid)
    if assignment is None or assignment["cruise_id"] != cruise["id"]:
        from errors import NOT_FOUND_IDS, err_not_found
        raise err_not_found(NOT_FOUND_IDS["assignment"], "Staff assignment not found")
    return cruise, assignment


@bp.post("/cruises/<cid>/staff-assignments/<aid>/confirm")
def confirm_assignment(cid, aid):
    require_auth(OM)
    cruise, assignment = _load_assignment(cid, aid)
    if assignment["status"] != "ASSIGNED":
        raise err_invalid_state("Assignment is not ASSIGNED")
    if cruise["status"] != "SCHEDULED":
        raise ApiError("ERR_CRUISE_NOT_BOOKABLE", 409, "Cruise is not SCHEDULED")
    if assignment["assigned_role"] == "BARTENDER":
        member = db.staff_members.get(assignment["staff_member_id"])
        expires = member.get("alcohol_cert_expires_at") if member else None
        if expires is None or clock.parse_dt(expires) <= clock.now():
            raise ApiError("ERR_ALCOHOL_CERT_EXPIRED", 409,
                           "BARTENDER confirmation requires an unexpired alcohol certification")
    assignment["status"] = "CONFIRMED"
    touch(assignment)
    svc.recompute_bar_service(cruise)
    return ok(_sz("assignment", assignment))


@bp.post("/cruises/<cid>/staff-assignments/<aid>/release")
def release_assignment(cid, aid):
    require_auth(OM)
    cruise, assignment = _load_assignment(cid, aid)
    if assignment["status"] not in ("ASSIGNED", "CONFIRMED"):
        raise err_invalid_state("Assignment is not ASSIGNED or CONFIRMED")
    assignment["status"] = "RELEASED"
    touch(assignment)
    svc.recompute_bar_service(cruise)
    return ok(_sz("assignment", assignment))
