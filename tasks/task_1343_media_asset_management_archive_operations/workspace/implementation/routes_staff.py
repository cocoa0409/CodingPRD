"""StaffMember registry."""
from flask import Blueprint, request

from auth import ALL_ROLES, require_roles
from db import STORE, new_id, stamp
from envelope import ok, paginate
from errors import raise_err
from serializers import staff_out
from validate import body, opt_bool, req_str

bp = Blueprint("staff", __name__, url_prefix="/archive")


@bp.post("/staff-members")
def create_staff():
    require_roles("SystemAdmin")
    j = body()
    email = req_str(j, "email")
    full_name = req_str(j, "full_name")
    department = req_str(j, "department")
    active = opt_bool(j, "active", True)
    for s in STORE.staff.values():
        if s["email"] == email:
            raise_err("ERR_DUPLICATE_STAFF_EMAIL", "A staff member with this email already exists")
    rec = {
        "id": new_id(),
        "email": email,
        "full_name": full_name,
        "department": department,
        "active": active,
    }
    stamp(rec)
    STORE.staff[rec["id"]] = rec
    return ok(staff_out(rec), 201)


@bp.get("/staff-members")
def list_staff():
    require_roles(*ALL_ROLES)
    recs = list(STORE.staff.values())
    email = request.args.get("email")
    if email is not None:
        recs = [r for r in recs if r["email"] == email]
    return paginate(recs, staff_out)


@bp.get("/staff-members/<sid>")
def get_staff(sid):
    require_roles(*ALL_ROLES)
    rec = STORE.staff.get(sid)
    if rec is None:
        raise_err("ERR_STAFF_MEMBER_NOT_FOUND", "Staff member not found")
    return ok(staff_out(rec))
