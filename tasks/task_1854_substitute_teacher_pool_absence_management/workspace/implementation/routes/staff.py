"""StaffMember endpoints: create, get, list per school."""

from flask import Blueprint

from db import STORE, new_entity, public
from errors import raise_err, ERR_SCHOOL_NOT_FOUND, ERR_STAFF_MEMBER_NOT_FOUND
from middleware import (
    auth_context, require_role, require_coordinator_school, ALL_ROLES,
)
from response import ok, paginated
from validate import body, req_str, req_enum, opt_bool

bp = Blueprint("staff", __name__)

GRADE_BANDS = ("ELEMENTARY", "MIDDLE", "HIGH")


@bp.route("/staff-members", methods=["POST"])
def create_staff_member():
    user_id, role = auth_context()
    data = body()
    school_id = req_str(data, "school_id")
    full_name = req_str(data, "full_name")
    subject = req_str(data, "subject")
    grade_band = req_enum(data, "grade_band", GRADE_BANDS)
    is_coordinator = opt_bool(data, "is_coordinator", False)
    require_role(role, ["DistrictAdmin", "SchoolCoordinator"])
    if role == "SchoolCoordinator":
        require_coordinator_school(user_id, school_id)
    if school_id not in STORE.schools:
        raise_err(ERR_SCHOOL_NOT_FOUND, "school id does not exist")
    m = new_entity(STORE.staff_members, {
        "school_id": school_id,
        "full_name": full_name,
        "subject": subject,
        "grade_band": grade_band,
        "is_coordinator": is_coordinator,
    })
    return ok(public(m), status=201)


@bp.route("/staff-members/<mid>", methods=["GET"])
def get_staff_member(mid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    m = STORE.staff_members.get(mid)
    if m is None:
        raise_err(ERR_STAFF_MEMBER_NOT_FOUND, "staff member id does not exist")
    return ok(public(m))


@bp.route("/schools/<sid>/staff-members", methods=["GET"])
def list_school_staff(sid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if sid not in STORE.schools:
        raise_err(ERR_SCHOOL_NOT_FOUND, "school id does not exist")
    items = sorted((m for m in STORE.staff_members.values() if m["school_id"] == sid),
                   key=lambda m: (m["created_at"], m["_seq"]))
    page, meta = paginated(items)
    return ok([public(m) for m in page], pagination=meta)
