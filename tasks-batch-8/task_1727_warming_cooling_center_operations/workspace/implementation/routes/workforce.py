"""Staff roster and shifts."""
import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_INVALID_WINDOW,
    ERR_SEGREGATION_OF_DUTIES, ERR_SHIFT_OVERLAP, ERR_SKILL_MISMATCH,
    ERR_VALIDATION,
)
from flask import Blueprint, g, request
from response import respond, respond_list
from services import ser_shift, ser_staff
from util import (
    body, opt_bool, paginate, req_dt, req_enum, req_list, req_str, touch,
)

bp = Blueprint("workforce", __name__)

SKILLS = ("INTAKE", "MEDICAL", "OUTREACH", "SITE_LEAD", "DRIVER")
SHIFT_ROLES = ("INTAKE", "MEDICAL", "OUTREACH", "SITE_LEAD", "GENERAL")


def get_staff(staff_id):
    s = db.store["staff"].get(staff_id)
    if s is None:
        raise_err(ERR_NOT_FOUND, f"StaffMember {staff_id} not found")
    return s


def get_shift(shift_id):
    sh = db.store["shifts"].get(shift_id)
    if sh is None:
        raise_err(ERR_NOT_FOUND, f"Shift {shift_id} not found")
    return sh


# ------------------------------------------------------------------- staff
@bp.route("/staff-members", methods=["POST"])
@require_roles("EOCManager")
def create_staff():
    b = body()
    full_name = req_str(b, "full_name")
    skills = req_list(b, "skills")
    for sk in skills:
        if sk not in SKILLS:
            raise_err(ERR_VALIDATION, f"Unknown skill: {sk}")
    active = opt_bool(b, "active", default=True)
    now = clock.now()
    s = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "full_name": full_name,
        "skills": list(skills),
        "active": active,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["staff"][s["id"]] = s
    return respond(ser_staff(s), 201)


@bp.route("/staff-members", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_staff():
    items = list(db.store["staff"].values())
    active_raw = request.args.get("active")
    if active_raw is not None:
        low = active_raw.lower()
        if low not in ("true", "false"):
            raise_err(ERR_VALIDATION, "active filter must be true or false")
        want = low == "true"
        items = [s for s in items if s["active"] == want]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    page, pagination = paginate([ser_staff(s) for s in items])
    return respond_list(page, pagination)


# ------------------------------------------------------------------ shifts
@bp.route("/site-activations/<act_id>/shifts", methods=["POST"])
@require_roles("SiteLead")
def create_shift(act_id):
    act = db.store["activations"].get(act_id)
    if act is None:
        raise_err(ERR_NOT_FOUND, f"SiteActivation {act_id} not found")
    b = body()
    staff = None
    if b.get("staff_member_id") is not None:
        staff = get_staff(b["staff_member_id"])
    if act["status"] not in ("OPENING", "OPEN"):
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot plan a shift on an activation in status {act['status']}",
        )
    if staff is None:
        req_str(b, "staff_member_id")  # raises ERR_VALIDATION when absent
        staff = get_staff(b["staff_member_id"])
    role_on_shift = req_enum(b, "role_on_shift", SHIFT_ROLES)
    start_at = req_dt(b, "start_at")
    end_at = req_dt(b, "end_at")
    if not staff["active"]:
        raise_err(
            ERR_INVALID_STATE,
            "Inactive staff cannot be assigned new shifts",
        )
    if end_at <= start_at:
        raise_err(ERR_INVALID_WINDOW, "end_at must be strictly after start_at")
    now = clock.now()
    sh = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "site_activation_id": act["id"],
        "staff_member_id": staff["id"],
        "role_on_shift": role_on_shift,
        "start_at": start_at,
        "end_at": end_at,
        "status": "PLANNED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["shifts"][sh["id"]] = sh
    return respond(ser_shift(sh), 201)


@bp.route("/shifts", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_shifts():
    items = list(db.store["shifts"].values())
    act_id = request.args.get("site_activation_id")
    staff_id = request.args.get("staff_member_id")
    status = request.args.get("status")
    if act_id is not None:
        items = [s for s in items if s["site_activation_id"] == act_id]
    if staff_id is not None:
        items = [s for s in items if s["staff_member_id"] == staff_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    page, pagination = paginate([ser_shift(s) for s in items])
    return respond_list(page, pagination)


@bp.route("/shifts/<shift_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_shift(shift_id):
    return respond(ser_shift(get_shift(shift_id)), 200)


@bp.route("/shifts/<shift_id>/confirm", methods=["POST"])
@require_roles("SiteLead")
def confirm_shift(shift_id):
    sh = get_shift(shift_id)
    act = db.store["activations"].get(sh["site_activation_id"])
    if act is None or act["status"] not in ("OPENING", "OPEN"):
        raise_err(
            ERR_INVALID_STATE,
            "Shift confirmation requires the activation to be OPENING or OPEN",
        )
    if sh["status"] != "PLANNED":
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot confirm a shift in status {sh['status']}",
        )
    staff = db.store["staff"].get(sh["staff_member_id"])
    if staff is None:
        raise_err(ERR_NOT_FOUND, f"StaffMember {sh['staff_member_id']} not found")
    if not staff["active"]:
        raise_err(ERR_INVALID_STATE, "Staff member is inactive")
    if (sh["role_on_shift"] != "GENERAL"
            and sh["role_on_shift"] not in staff["skills"]):
        raise_err(
            ERR_SKILL_MISMATCH,
            f"Staff member lacks skill {sh['role_on_shift']}",
        )
    if g.user_id == sh["staff_member_id"]:
        raise_err(
            ERR_SEGREGATION_OF_DUTIES,
            "A staff member cannot confirm their own shift",
        )
    for other in db.store["shifts"].values():
        if (other["id"] != sh["id"]
                and other["staff_member_id"] == sh["staff_member_id"]
                and other["status"] == "CONFIRMED"
                and other["start_at"] < sh["end_at"]
                and sh["start_at"] < other["end_at"]):
            raise_err(
                ERR_SHIFT_OVERLAP,
                "Another CONFIRMED shift of this staff member intersects "
                "this window",
            )
    sh["status"] = "CONFIRMED"
    touch(sh)
    return respond(ser_shift(sh), 200)


@bp.route("/shifts/<shift_id>/cancel", methods=["POST"])
@require_roles("SiteLead")
def cancel_shift(shift_id):
    sh = get_shift(shift_id)
    if sh["status"] not in ("PLANNED", "CONFIRMED"):
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot cancel a shift in status {sh['status']}",
        )
    sh["status"] = "CANCELLED"
    touch(sh)
    return respond(ser_shift(sh), 200)
