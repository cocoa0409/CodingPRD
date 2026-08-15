"""Inspector shift + production day endpoints."""

from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request

from db import store, new_id
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from validation import get_body, req_string, req_enum, req_iso_datetime, req_date
from errors import (raise_error, ERR_NOT_FOUND, ERR_SHIFT_WINDOW_CONFLICT,
                    ERR_CHECKIN_IDENTITY_MISMATCH, ERR_SHIFT_INVALID_STATE,
                    ERR_SHIFT_CHECKIN_OUTSIDE_WINDOW, ERR_DAY_INVALID_STATE,
                    ERR_PLANT_SUSPENDED, ERR_INSPECTOR_NOT_PRESENT,
                    ERR_DAY_DATE_MISMATCH, ERR_PLAN_NOT_EFFECTIVE,
                    ERR_DUPLICATE_PRODUCTION_DAY)
from serializers import shift_out, day_out
from services import touch, recompute_day_posture, recompute_day_totals, round2

bp = Blueprint("shifts_days", __name__)

READ_ROLES = ("PlantAdmin", "QAManager", "QATech", "LabAnalyst", "Inspector", "ProductionManager")
PROCESS_TYPES = {"SLAUGHTER", "RAW_GROUND", "RAW_INTACT", "COOKED_RTE"}


# ---------------------------------------------------------------------------
# Inspector shifts
# ---------------------------------------------------------------------------

@bp.route("/plants/<pid>/inspector-shifts", methods=["POST"])
def create_shift(pid):
    user_id, _ = require_roles("PlantAdmin")
    body = get_body()
    inspector_user_id = req_string(body, "inspector_user_id")
    scheduled_start = req_iso_datetime(body, "scheduled_start")
    scheduled_end = req_iso_datetime(body, "scheduled_end")
    if not (scheduled_start < scheduled_end):
        from errors import ERR_INVALID_REQUEST
        raise_error(ERR_INVALID_REQUEST, "scheduled_start must be strictly before scheduled_end")

    plant = store.plants.get(pid)
    if not plant:
        raise_error(ERR_NOT_FOUND, "Plant not found")

    # Half-open [start, end) overlap check against SCHEDULED/ON_PREMISE shifts of same inspector
    for s in store.inspector_shifts.values():
        if s["inspector_user_id"] != inspector_user_id:
            continue
        if s["status"] not in ("SCHEDULED", "ON_PREMISE"):
            continue
        # Overlap iff new_start < existing_end AND existing_start < new_end
        if scheduled_start < s["scheduled_end"] and s["scheduled_start"] < scheduled_end:
            raise_error(ERR_SHIFT_WINDOW_CONFLICT, "Shift overlaps an existing shift for this inspector")

    now = store.now_iso()
    shift = {
        "id": new_id(),
        "plant_id": pid,
        "inspector_user_id": inspector_user_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "checked_in_at": None,
        "checked_out_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.inspector_shifts[shift["id"]] = shift
    return success_object(shift_out(shift), 201)


@bp.route("/inspector-shifts/<sid>", methods=["GET"])
def get_shift(sid):
    require_roles(*READ_ROLES)
    shift = store.inspector_shifts.get(sid)
    if not shift:
        raise_error(ERR_NOT_FOUND, "Shift not found")
    return success_object(shift_out(shift))


@bp.route("/inspector-shifts", methods=["GET"])
def list_shifts():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    plant_id = request.args.get("plant_id")
    inspector_user_id = request.args.get("inspector_user_id")
    status = request.args.get("status")
    items = sorted(store.inspector_shifts.values(), key=lambda s: (s["created_at"], s["id"]))
    if plant_id is not None:
        items = [s for s in items if s["plant_id"] == plant_id]
    if inspector_user_id is not None:
        items = [s for s in items if s["inspector_user_id"] == inspector_user_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([shift_out(s) for s in page], limit, offset, total)


@bp.route("/inspector-shifts/<sid>/check-in", methods=["POST"])
def check_in(sid):
    user_id, _ = require_roles("Inspector")
    get_body()
    shift = store.inspector_shifts.get(sid)
    if not shift:
        raise_error(ERR_NOT_FOUND, "Shift not found")
    # Identity check first (priority 3)
    if user_id != shift["inspector_user_id"]:
        raise_error(ERR_CHECKIN_IDENTITY_MISMATCH, "X-User-ID does not match the shift's inspector_user_id")
    # From-state (priority 13)
    if shift["status"] != "SCHEDULED":
        raise_error(ERR_SHIFT_INVALID_STATE, "Shift must be SCHEDULED to check in")
    # Window: [scheduled_start - 15min, scheduled_end] inclusive (priority 21)
    now = store.now()
    window_start = shift["scheduled_start"] - timedelta(minutes=15)
    if not (window_start <= now <= shift["scheduled_end"]):
        raise_error(ERR_SHIFT_CHECKIN_OUTSIDE_WINDOW, "Check-in outside the allowed window")
    shift["status"] = "ON_PREMISE"
    shift["checked_in_at"] = store.now_iso()
    touch(shift)
    return success_object(shift_out(shift))


@bp.route("/inspector-shifts/<sid>/check-out", methods=["POST"])
def check_out(sid):
    user_id, _ = require_roles("Inspector")
    get_body()
    shift = store.inspector_shifts.get(sid)
    if not shift:
        raise_error(ERR_NOT_FOUND, "Shift not found")
    if user_id != shift["inspector_user_id"]:
        raise_error(ERR_CHECKIN_IDENTITY_MISMATCH, "X-User-ID does not match the shift's inspector_user_id")
    if shift["status"] != "ON_PREMISE":
        raise_error(ERR_SHIFT_INVALID_STATE, "Shift must be ON_PREMISE to check out")
    shift["status"] = "DEPARTED"
    shift["checked_out_at"] = store.now_iso()
    touch(shift)
    # Conditional cascade: if no other ON_PREMISE shift for the plant, suspend OPEN days
    plant_id = shift["plant_id"]
    still_covered = any(
        s["plant_id"] == plant_id and s["status"] == "ON_PREMISE" and s["id"] != sid
        for s in store.inspector_shifts.values()
    )
    if not still_covered:
        for day in store.production_days.values():
            if day["plant_id"] == plant_id and day["status"] == "OPEN":
                day["status"] = "SUSPENDED"
                touch(day)
    return success_object(shift_out(shift))


# ---------------------------------------------------------------------------
# Production days
# ---------------------------------------------------------------------------

@bp.route("/plants/<pid>/production-days", methods=["POST"])
def create_day(pid):
    user_id, _ = require_roles("ProductionManager")
    body = get_body()
    production_date = req_date(body, "production_date")
    process_type = req_enum(body, "process_type", PROCESS_TYPES)
    plant = store.plants.get(pid)
    if not plant:
        raise_error(ERR_NOT_FOUND, "Plant not found")
    # At most one non-CLOSED day per (plant, production_date)
    for d in store.production_days.values():
        if d["plant_id"] == pid and d["production_date"] == production_date and d["status"] != "CLOSED":
            raise_error(ERR_DUPLICATE_PRODUCTION_DAY, "A non-CLOSED day already exists for this date")
    now = store.now_iso()
    day = {
        "id": new_id(),
        "plant_id": pid,
        "production_date": production_date,
        "process_type": process_type,
        "status": "PLANNED",
        "posture": "CLEAR",
        "total_cut_weight_lbs": 0,
        "total_cold_weight_lbs": 0,
        "day_yield_pct": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.production_days[day["id"]] = day
    return success_object(day_out(day), 201)


def _get_day(day_id):
    day = store.production_days.get(day_id)
    if not day:
        raise_error(ERR_NOT_FOUND, "Production day not found")
    return day


@bp.route("/production-days/<did>", methods=["GET"])
def get_day(did):
    require_roles(*READ_ROLES)
    return success_object(day_out(_get_day(did)))


@bp.route("/production-days", methods=["GET"])
def list_days():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    plant_id = request.args.get("plant_id")
    production_date = request.args.get("production_date")
    status = request.args.get("status")
    items = sorted(store.production_days.values(), key=lambda d: (d["created_at"], d["id"]))
    if plant_id is not None:
        items = [d for d in items if d["plant_id"] == plant_id]
    if production_date is not None:
        items = [d for d in items if d["production_date"] == production_date]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([day_out(d) for d in page], limit, offset, total)


def _open_gates(day):
    """Business gates for open/resume, in fixed order."""
    plant = store.plants[day["plant_id"]]
    if plant["operating_status"] != "ACTIVE":
        raise_error(ERR_PLANT_SUSPENDED, "Plant operating_status is SUSPENDED")
    covered = any(
        s["plant_id"] == day["plant_id"] and s["status"] == "ON_PREMISE"
        for s in store.inspector_shifts.values()
    )
    if not covered:
        raise_error(ERR_INSPECTOR_NOT_PRESENT, "No inspector shift is ON_PREMISE")
    today = store.now().strftime("%Y-%m-%d")
    if today != day["production_date"]:
        raise_error(ERR_DAY_DATE_MISMATCH, "Logical clock date does not match production_date")
    effective = any(
        p["plant_id"] == day["plant_id"] and p["process_type"] == day["process_type"] and p["status"] == "EFFECTIVE"
        for p in store.haccp_plans.values()
    )
    if not effective:
        raise_error(ERR_PLAN_NOT_EFFECTIVE, "No EFFECTIVE HACCP plan for this process type")


@bp.route("/production-days/<did>/open", methods=["POST"])
def open_day(did):
    user_id, _ = require_roles("ProductionManager")
    get_body()
    day = _get_day(did)
    if day["status"] not in ("PLANNED", "SUSPENDED"):
        raise_error(ERR_DAY_INVALID_STATE, "Day must be PLANNED or SUSPENDED to open")
    _open_gates(day)
    day["status"] = "OPEN"
    touch(day)
    recompute_day_posture(did)
    return success_object(day_out(day))


@bp.route("/production-days/<did>/suspend", methods=["POST"])
def suspend_day(did):
    user_id, _ = require_roles("ProductionManager")
    get_body()
    day = _get_day(did)
    if day["status"] != "OPEN":
        raise_error(ERR_DAY_INVALID_STATE, "Day must be OPEN to suspend")
    day["status"] = "SUSPENDED"
    touch(day)
    return success_object(day_out(day))


@bp.route("/production-days/<did>/close", methods=["POST"])
def close_day(did):
    user_id, _ = require_roles("ProductionManager")
    get_body()
    day = _get_day(did)
    if day["status"] not in ("OPEN", "SUSPENDED"):
        raise_error(ERR_DAY_INVALID_STATE, "Day must be OPEN or SUSPENDED to close")
    # Block while unresolved deviations exist
    for dv in store.deviations.values():
        if dv["production_day_id"] == did and dv["status"] in ("OPEN", "ACTION_LOGGED"):
            raise_error(ERR_DAY_INVALID_STATE, "Day has unresolved deviations")
    # All lots must be FABRICATED or CONDEMNED
    for lot in store.carcass_lots.values():
        if lot["production_day_id"] == did and lot["status"] not in ("FABRICATED", "CONDEMNED"):
            raise_error(ERR_DAY_INVALID_STATE, "Day has non-terminal lots")
    # Freeze reconciliation over FABRICATED lots
    recompute_day_totals(did)
    day = store.production_days[did]
    cold = day["total_cold_weight_lbs"]
    if cold == 0:
        day["day_yield_pct"] = None
    else:
        # PRD §3.3: 100 * frozen cut total / frozen cold total, rounded once.
        day["day_yield_pct"] = round2(
            Decimal("100") * Decimal(str(day["total_cut_weight_lbs"])) / Decimal(str(cold))
        )
    day["status"] = "CLOSED"
    touch(day)
    return success_object(day_out(day))
