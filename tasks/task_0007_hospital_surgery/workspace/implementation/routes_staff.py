from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_STAFF_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_TIME_PARAMETERS
from middleware import auth_required
from response import success, paginate
from serialize import serialize_staff
from utils import get_json_body, require_str, require_number, require_int, optional_bool, get_pagination

STAFF_ROLES = {"ANESTHESIOLOGIST", "SCRUB_NURSE", "CIRCULATING_NURSE"}
QUALIFICATIONS = {"GENERAL", "CARDIAC", "NEURO", "OBSTETRIC", "PEDIATRIC"}

bp = Blueprint("staff", __name__)


@bp.route("/staff", methods=["POST"])
@auth_required("Scheduler")
def create_staff():
    body = get_json_body()
    staff_name = require_str(body, "staff_name")
    staff_role = require_str(body, "staff_role")
    if staff_role not in STAFF_ROLES:
        raise_error(ERR_INVALID_REQUEST, f"staff_role must be one of {sorted(STAFF_ROLES)}")
    quals = body.get("qualifications")
    if quals is None:
        raise_error(ERR_INVALID_REQUEST, "Missing required field 'qualifications'")
    if not isinstance(quals, list):
        raise_error(ERR_INVALID_REQUEST, "qualifications must be a list")
    for q in quals:
        if not isinstance(q, str) or q not in QUALIFICATIONS:
            raise_error(ERR_INVALID_REQUEST,
                        f"qualifications entries must be in {sorted(QUALIFICATIONS)}")
    hourly_rate = require_number(body, "hourly_rate")
    shift_start = require_int(body, "shift_start_minute", allow_negative=True)
    shift_end = require_int(body, "shift_end_minute", allow_negative=True)
    if shift_end <= shift_start:
        raise_error(ERR_INVALID_TIME_PARAMETERS,
                    "shift_end_minute must be strictly greater than shift_start_minute")
    on_call = optional_bool(body, "on_call", False)

    with db.lock:
        s = {
            "staff_name": staff_name,
            "staff_role": staff_role,
            "qualifications": quals,
            "hourly_rate": hourly_rate,
            "shift_start_minute": shift_start,
            "shift_end_minute": shift_end,
            "on_call": on_call,
        }
        db.stamp_create(s)
        db.staff_members[s["id"]] = s
    return success(serialize_staff(s), status_code=201)


@bp.route("/staff", methods=["GET"])
@auth_required("Any")
def list_staff():
    limit, offset = get_pagination()
    role_filter = request.args.get("staff_role")
    with db.lock:
        items = sorted(db.staff_members.values(), key=lambda r: (r["created_at"], r["_seq"]))
        if role_filter:
            items = [r for r in items if r["staff_role"] == role_filter]
        sliced, pagination = paginate(items, limit, offset)
        data = [serialize_staff(r) for r in sliced]
    return success(data, response_type="array", pagination=pagination)


@bp.route("/staff/<staff_id>", methods=["GET"])
@auth_required("Any")
def get_staff(staff_id):
    with db.lock:
        s = db.staff_members.get(staff_id)
        if s is None:
            raise_error(ERR_STAFF_NOT_FOUND, f"StaffMember {staff_id} not found")
        return success(serialize_staff(s))
