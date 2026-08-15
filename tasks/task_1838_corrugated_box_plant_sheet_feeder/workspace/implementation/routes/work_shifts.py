"""WorkShift endpoints."""
from flask import Blueprint

from db import db
from errors import err_invalid_request, err_invalid_state, err_not_found
from middleware import require_roles
from response import success_object
from services.calcs import bump, recompute_shift_rollup
from services.cascade import cancel_shift_cascade
from services.serialize import serialize_work_shift
from util import is_int, new_id, utcnow_iso
from ._helpers import get_json_body, require_fields

bp = Blueprint("work_shifts", __name__)

ALL_ROLES = ("PlantAdmin", "SalesRep", "ProductionPlanner", "CustomerService", "ClaimsAdjuster", "Customer")
MACHINE_CODES = {"CORRUGATOR", "DIE_CUTTER", "FFG"}


@bp.route("/api/work-shifts", methods=["POST"])
@require_roles("ProductionPlanner")
def create_work_shift(_user_id, _role):
    body = get_json_body()
    require_fields(body, ["machine_code", "shift_date", "start_minute", "end_minute"])

    machine_code = body["machine_code"]
    shift_date = body["shift_date"]
    start_minute = body["start_minute"]
    end_minute = body["end_minute"]

    if machine_code not in MACHINE_CODES:
        raise err_invalid_request("machine_code must be CORRUGATOR, DIE_CUTTER, or FFG")
    if not isinstance(shift_date, str) or not shift_date.strip():
        raise err_invalid_request("shift_date must be an ISO date string")
    from util import parse_date
    if parse_date(shift_date) is None:
        raise err_invalid_request("shift_date must be a valid ISO date (YYYY-MM-DD)")
    if not is_int(start_minute) or start_minute < 0:
        raise err_invalid_request("start_minute must be an integer >= 0")
    if not is_int(end_minute) or end_minute <= start_minute:
        raise err_invalid_request("end_minute must be > start_minute")

    now = utcnow_iso()
    sid = new_id()
    capacity = end_minute - start_minute
    shift = {
        "id": sid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "machine_code": machine_code,
        "shift_date": shift_date,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "capacity_minutes": capacity,
        "scheduled_minutes": 0,
        "available_minutes": capacity,
        "status": "OPEN",
    }
    db.work_shifts[sid] = shift
    return success_object(serialize_work_shift(shift), 201)


@bp.route("/api/work-shifts/<sid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_work_shift(sid, _user_id, _role):
    s = db.work_shifts.get(sid)
    if s is None:
        raise err_not_found("work shift not found")
    return success_object(serialize_work_shift(s), 200)


@bp.route("/api/work-shifts/<sid>/cancel", methods=["POST"])
@require_roles("ProductionPlanner")
def cancel_work_shift(sid, _user_id, _role):
    s = db.work_shifts.get(sid)
    if s is None:
        raise err_not_found("work shift not found")
    if s["status"] != "OPEN":
        raise err_invalid_state("work shift is not OPEN")
    s["status"] = "CANCELLED"
    cancel_shift_cascade(s)
    bump(s)
    return success_object(serialize_work_shift(s), 200)
