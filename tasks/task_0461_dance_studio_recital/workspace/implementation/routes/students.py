"""Student routes (PRD 3.1, 3.4)."""
from flask import Blueprint

from db import common_fields, db, new_id, touch
from helpers import (LEVELS, lookup, paginate, parse_date, require_enum,
                     require_fields, require_str, sort_by_created)
from middleware import authenticate, get_json, require_owner
from response import success
from services.enrollment import drop_enrollment
from services.tuition import recompute_family
from views import public, public_list

bp = Blueprint("students", __name__)


def age_as_of(birth_date, cutoff_date):
    """Whole years floored against a cutoff date (PRD 3.3 / student_age_as_of_cutoff)."""
    age = cutoff_date.year - birth_date.year
    if (cutoff_date.month, cutoff_date.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


@bp.route("/families/<fid>/students", methods=["POST"])
def add_student(fid):
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    fam = lookup(db.families, fid)
    require_owner(role, user_id, fam["id"])
    body = get_json()
    require_fields(body, ["full_name", "birth_date", "level"])
    full_name = require_str(body, "full_name")
    birth = parse_date(body, "birth_date")
    level = require_enum(body, "level", set(LEVELS))
    st = {
        "id": new_id(),
        "family_id": fam["id"],
        "full_name": full_name,
        "birth_date": body["birth_date"],
        "age_as_of_cutoff": 0,
        "level": level,
        "status": "ACTIVE",
        **common_fields(),
    }
    st["_birth"] = birth  # internal helper not serialized
    db.students[st["id"]] = st
    recompute_family(fam["id"])
    return success(public(st), status=201)


@bp.route("/families/<fid>/students", methods=["GET"])
def list_family_students(fid):
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    fam = lookup(db.families, fid)
    require_owner(role, user_id, fam["id"])
    items = [s for s in db.students.values() if s["family_id"] == fam["id"]]
    items = sort_by_created(items)
    page, pg = paginate(items)
    return success(public_list(page), status=200, is_array=True, pagination=pg)


@bp.route("/students/<sid>", methods=["GET"])
def get_student(sid):
    user_id, role = authenticate({"StudioAdmin", "Parent", "Instructor"})
    st = lookup(db.students, sid)
    require_owner(role, user_id, st["family_id"])
    return success(public(st), status=200)


@bp.route("/students/<sid>/withdraw", methods=["POST"])
def withdraw_student(sid):
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    st = lookup(db.students, sid)
    require_owner(role, user_id, st["family_id"])
    if st["status"] != "ACTIVE":
        from errors import err
        raise err("ERR_INVALID_STATE", "Student is not ACTIVE.")
    st["status"] = "WITHDRAWN"
    touch(st)
    # Drop each enrollment in CONFIRMED/WAITLIST_PROMOTED (full cascade) and
    # each purely WAITLISTED.
    enrs = [e for e in db.enrollments.values() if e["student_id"] == st["id"]]
    # Process occupied first then waitlisted, to mirror the normal drop cascade.
    for e in sorted(enrs, key=lambda x: (x["created_at"], x["_seq"])):
        if e["placement_status"] in {"CONFIRMED", "WAITLIST_PROMOTED", "WAITLISTED"}:
            drop_enrollment(e)
    recompute_family(st["family_id"])
    return success(public(st), status=200)
