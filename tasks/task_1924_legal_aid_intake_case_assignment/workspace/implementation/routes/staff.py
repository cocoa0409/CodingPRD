"""StaffMember onboarding, updates, and caseload read (PRD section 3.6)."""
from flask import Blueprint, request

from db import db, new_id
from errors import (ERR_INVALID_SUPERVISOR, ERR_STAFF_HAS_OPEN_CASES, fail)
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services.common import get_or_404, list_response, stamp_new, touch
from services.enums import CASE_TYPES, STAFF_STATUSES, STAFF_TYPES
from services.serialize import caseload_json, staff_json
from validators import (body, check_allowed, opt_enum, opt_int, opt_list,
                        opt_str, req_enum, req_list, req_str)

bp = Blueprint("staff", __name__)


def _supervision_error():
    fail(ERR_INVALID_SUPERVISOR,
         "supervising_attorney_id must reference an ATTORNEY and the "
         "supervision chain must be acyclic")


def _creates_cycle(member_id, supervisor_id):
    """Following the chain from supervisor_id must never reach member_id."""
    seen = {member_id}
    cur = supervisor_id
    while cur is not None:
        if cur in seen:
            return True
        seen.add(cur)
        nxt = db.staff.get(cur)
        cur = nxt["supervising_attorney_id"] if nxt is not None else None
    return False


def _validate_supervision(member_id, staff_type, supervisor_id):
    """member_id may be None on create."""
    if supervisor_id is None:
        if staff_type == "PARALEGAL":
            _supervision_error()
        return
    supervisor = get_or_404(db.staff, supervisor_id)  # body FK existence
    if supervisor["staff_type"] != "ATTORNEY":
        _supervision_error()
    if member_id is not None and _creates_cycle(member_id, supervisor_id):
        _supervision_error()


@bp.route("/staff-members", methods=["POST"])
@require_roles(["ProgramDirector"])
def create_staff():
    b = body()
    check_allowed(b, ["full_name", "staff_type", "admitted_counties",
                      "practice_areas", "max_units",
                      "supervising_attorney_id"])
    full_name = req_str(b, "full_name")
    staff_type = req_enum(b, "staff_type", STAFF_TYPES)
    admitted_counties = req_list(b, "admitted_counties")
    practice_areas = req_list(b, "practice_areas", enum_values=CASE_TYPES)
    max_units = opt_int(b, "max_units", default=40, min_v=1)
    supervisor_id = b.get("supervising_attorney_id")
    if supervisor_id is not None and not isinstance(supervisor_id, str):
        from errors import ERR_INVALID_REQUEST
        fail(ERR_INVALID_REQUEST,
             "Field supervising_attorney_id must be a string")
    _validate_supervision(None, staff_type, supervisor_id)
    rec = {
        "id": new_id(),
        "full_name": full_name,
        "staff_type": staff_type,
        "admitted_counties": admitted_counties,
        "practice_areas": practice_areas,
        "max_units": max_units,
        "supervising_attorney_id": supervisor_id,
        "status": "ACTIVE",
    }
    stamp_new(rec)
    db.staff[rec["id"]] = rec
    return ok_object(staff_json(rec), 201)


@bp.route("/staff-members/<sid>", methods=["GET"])
@require_roles(ALL_ROLES)
def get_staff(sid):
    return ok_object(staff_json(get_or_404(db.staff, sid)))


@bp.route("/staff-members", methods=["GET"])
@require_roles(ALL_ROLES)
def list_staff():
    records = list(db.staff.values())
    for param in ("supervising_attorney_id", "staff_type", "status"):
        value = request.args.get(param)
        if value is not None:
            records = [m for m in records if m[param] == value]
    practice_area = request.args.get("practice_area")
    if practice_area is not None:
        records = [m for m in records if practice_area in m["practice_areas"]]
    county = request.args.get("county")
    if county is not None:
        records = [m for m in records if county in m["admitted_counties"]]
    return list_response(records, staff_json)


@bp.route("/staff-members/<sid>", methods=["PATCH"])
@require_roles(["ProgramDirector"])
def update_staff(sid):
    rec = get_or_404(db.staff, sid)
    b = body()
    check_allowed(b, ["full_name", "max_units", "status", "admitted_counties",
                      "practice_areas", "supervising_attorney_id"])
    updates = {}
    if "full_name" in b:
        v = opt_str(b, "full_name")
        if v is not None:
            updates["full_name"] = v
    if "max_units" in b:
        v = opt_int(b, "max_units", min_v=1)
        if v is not None:
            updates["max_units"] = v
    if "status" in b:
        v = opt_enum(b, "status", STAFF_STATUSES)
        if v is not None:
            updates["status"] = v
    if "admitted_counties" in b:
        v = opt_list(b, "admitted_counties")
        if v is not None:
            updates["admitted_counties"] = v
    if "practice_areas" in b:
        v = opt_list(b, "practice_areas", enum_values=CASE_TYPES)
        if v is not None:
            updates["practice_areas"] = v
    supervisor_changed = "supervising_attorney_id" in b
    if supervisor_changed:
        v = b["supervising_attorney_id"]
        if v is not None and not isinstance(v, str):
            from errors import ERR_INVALID_REQUEST
            fail(ERR_INVALID_REQUEST,
                 "Field supervising_attorney_id must be a string")
        updates["supervising_attorney_id"] = v

    effective_supervisor = (updates["supervising_attorney_id"]
                            if supervisor_changed
                            else rec["supervising_attorney_id"])
    _validate_supervision(rec["id"], rec["staff_type"], effective_supervisor)

    if updates.get("status", rec["status"]) == "SEPARATED":
        for c in db.cases.values():
            if c["status"] in ("OPEN", "ON_HOLD") and (
                    c["assigned_attorney_id"] == rec["id"]
                    or c["assigned_paralegal_id"] == rec["id"]):
                fail(ERR_STAFF_HAS_OPEN_CASES,
                     "Member still has OPEN or ON_HOLD cases assigned")

    rec.update(updates)
    touch(rec)
    return ok_object(staff_json(rec))


@bp.route("/staff-members/<sid>/caseload", methods=["GET"])
@require_roles(ALL_ROLES)
def get_caseload(sid):
    return ok_object(caseload_json(get_or_404(db.staff, sid)))
