"""LaborShift endpoints: create/assign/confirm/complete/no-show with C4."""
from flask import Blueprint

from db import DB, new_id, next_seq
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok
from services import SHIFT_ROLES, c4_allocate, get_hall, get_shift, ser, stamp, touch
from util import as_enum, as_int, as_iso_date, as_str, body, parse_ymd, required
from routes.common import list_endpoint

bp = Blueprint("shifts", __name__)

_REST_BUFFER_MINUTES = 480
_ACTIVE_STATUSES = ("ASSIGNED", "CONFIRMED", "COMPLETED")


def _abs_minutes(shift_date, minute):
    return parse_ymd(shift_date).toordinal() * 1440 + minute


def _check_overlap(staff_ref, shift_date, start, end, exclude_id=None):
    """Tier 7: half-open interval overlap on the same shift_date."""
    for s in DB["labor_shifts"].values():
        if s["id"] == exclude_id:
            continue
        if s["staff_ref"] != staff_ref or s["shift_date"] != shift_date:
            continue
        if s["status"] not in _ACTIVE_STATUSES:
            continue
        if start < s["end_minute"] and s["start_minute"] < end:
            raise ApiError(
                "ERR_SHIFT_OVERLAP",
                409,
                "Shift overlaps another shift of this staff member",
            )


def _check_rest(staff_ref, shift_date, start, exclude_id=None):
    """Tier 8: >= 480 minutes between any prior shift's end and this start."""
    new_start = _abs_minutes(shift_date, start)
    for s in DB["labor_shifts"].values():
        if s["id"] == exclude_id:
            continue
        if s["staff_ref"] != staff_ref:
            continue
        if s["status"] not in _ACTIVE_STATUSES:
            continue
        prior_end = _abs_minutes(s["shift_date"], s["end_minute"])
        if prior_end <= new_start and new_start - prior_end < _REST_BUFFER_MINUTES:
            raise ApiError(
                "ERR_REST_PERIOD_VIOLATION",
                422,
                "Less than 480 minutes since the staff member's prior shift",
            )


@bp.post("/labor-shifts")
def create_shift():
    auth(["HallManager"])
    data = body()
    dining_hall_id = required(data, "dining_hall_id")
    if isinstance(dining_hall_id, str):
        get_hall(dining_hall_id)
    # Fields needed for the tier 7/8 guards are parsed first.
    staff_ref = data.get("staff_ref")
    if staff_ref is not None:
        as_str(staff_ref, "staff_ref")
    shift_date = required(data, "shift_date")
    start_minute = required(data, "start_minute")
    end_minute = required(data, "end_minute")
    if isinstance(shift_date, str) and isinstance(start_minute, int) and not isinstance(
        start_minute, bool
    ) and isinstance(end_minute, int) and not isinstance(end_minute, bool):
        try:
            parse_ymd(shift_date)
            well_formed = True
        except Exception:
            well_formed = False
    else:
        well_formed = False
    if staff_ref is not None and well_formed:
        _check_overlap(staff_ref, shift_date, start_minute, end_minute)
        _check_rest(staff_ref, shift_date, start_minute)
    # Tier 10 field shape.
    shift_date = as_iso_date(shift_date, "shift_date")
    role = as_enum(required(data, "role"), "role", SHIFT_ROLES)
    start_minute = as_int(start_minute, "start_minute")
    if not 0 <= start_minute <= 1439:
        raise ApiError("ERR_VALIDATION", 400, "start_minute must be in [0, 1439]")
    end_minute = as_int(end_minute, "end_minute")
    if not (start_minute < end_minute <= 1440):
        raise ApiError(
            "ERR_VALIDATION", 400, "end_minute must satisfy start_minute < end <= 1440"
        )
    rate = as_int(required(data, "hourly_rate_cents"), "hourly_rate_cents")
    if rate <= 0:
        raise ApiError("ERR_VALIDATION", 400, "hourly_rate_cents must be > 0")
    if not isinstance(dining_hall_id, str):
        raise ApiError("ERR_VALIDATION", 400, "dining_hall_id must be a string")
    rec = {
        "id": new_id(),
        "dining_hall_id": dining_hall_id,
        "staff_ref": staff_ref,
        "role": role,
        "shift_date": shift_date,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "hourly_rate_cents": rate,
        "status": "ASSIGNED" if staff_ref is not None else "PLANNED",
        "worked_minutes": None,
        "regular_minutes": 0,
        "overtime_minutes": 0,
        "regular_pay_cents": 0,
        "overtime_pay_cents": 0,
        "_seq": next_seq(),
    }
    stamp(rec)
    DB["labor_shifts"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@bp.get("/labor-shifts")
def list_shifts():
    return list_endpoint(
        "labor_shifts",
        [
            ("dining_hall_id", "dining_hall_id"),
            ("staff_ref", "staff_ref"),
            ("shift_date", "shift_date"),
            ("status", "status"),
        ],
    )


@bp.get("/labor-shifts/<sid>")
def get_one_shift(sid):
    auth(ALL_ROLES)
    return ok(ser(get_shift(sid)))


@bp.post("/labor-shifts/<sid>/assign")
def assign_shift(sid):
    auth(["HallManager"])
    shift = get_shift(sid)
    if shift["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Shift is not PLANNED")
    data = body()
    staff_ref = as_str(required(data, "staff_ref"), "staff_ref")
    _check_overlap(
        staff_ref, shift["shift_date"], shift["start_minute"], shift["end_minute"],
        exclude_id=shift["id"],
    )
    _check_rest(staff_ref, shift["shift_date"], shift["start_minute"], exclude_id=shift["id"])
    shift["staff_ref"] = staff_ref
    shift["status"] = "ASSIGNED"
    touch(shift)
    return ok(ser(shift))


@bp.post("/labor-shifts/<sid>/confirm")
def confirm_shift(sid):
    auth(["HallManager"])
    shift = get_shift(sid)
    if shift["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Shift is not ASSIGNED")
    hall = get_hall(shift["dining_hall_id"])
    if hall["status"] != "ACTIVE":
        raise ApiError("ERR_HALL_SUSPENDED", 409, "Dining hall is not ACTIVE")
    shift["status"] = "CONFIRMED"
    touch(shift)
    return ok(ser(shift))


@bp.post("/labor-shifts/<sid>/complete")
def complete_shift(sid):
    auth(["HallManager"])
    shift = get_shift(sid)
    if shift["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "Shift is not CONFIRMED")
    data = body()
    worked = as_int(required(data, "worked_minutes"), "worked_minutes")
    if not 1 <= worked <= (shift["end_minute"] - shift["start_minute"]) + 60:
        raise ApiError("ERR_VALIDATION", 400, "worked_minutes out of range")
    shift["worked_minutes"] = worked
    shift["status"] = "COMPLETED"
    c4_allocate(shift)
    touch(shift)
    return ok(ser(shift))


@bp.post("/labor-shifts/<sid>/mark-no-show")
def no_show_shift(sid):
    auth(["HallManager"])
    shift = get_shift(sid)
    if shift["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "Shift is not CONFIRMED")
    shift["status"] = "NO_SHOW"
    touch(shift)
    return ok(ser(shift))
