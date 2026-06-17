"""Admission lifecycle endpoints (PRD §3.4, §3.5)."""
from flask import Blueprint, request

import errors
from db import db, touch
from errors import ApiError
from middleware import authenticate, require_role
from response import success, list_success
from services import serialize
from services.calculations import band_color, freeze_episode_days, MAX_FREEZE_DAYS
from services.common import (
    get_json_body, require_int, parse_pagination, paginate, parse_datetime,
)
from services.lookup import get_admission, get_entry_window, get_guest, require_owner

bp = Blueprint("admissions", __name__)


def _order_of(adm):
    return db.orders.get(adm["order_id"])


def _owner_guest_id(adm):
    """Ownership for a guest-scoped admission mutation maps to the parent order's guest."""
    order = _order_of(adm)
    return order["guest_id"] if order else None


@bp.route("/admissions/<aid>", methods=["GET"])
def get_admission_route(aid):
    _, role = authenticate()
    require_role(role, {"Guest", "GateAgent", "ParkManager", "FinanceClerk"})
    rec = get_admission(aid)
    return success(serialize.admission(rec))


@bp.route("/admissions", methods=["GET"])
def list_admissions():
    _, role = authenticate()
    require_role(role, {"Guest", "GateAgent", "ParkManager", "FinanceClerk"})
    limit, offset = parse_pagination()
    rows = list(db.admissions.values())
    entry_window_id = request.args.get("entry_window_id")
    guest_id = request.args.get("guest_id")
    park_id = request.args.get("park_id")
    status = request.args.get("status")
    if entry_window_id is not None:
        rows = [a for a in rows if a["entry_window_id"] == entry_window_id]
    if guest_id is not None:
        rows = [a for a in rows if a["guest_id"] == guest_id]
    if park_id is not None:
        rows = [a for a in rows if a["park_id"] == park_id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_success([serialize.admission(r) for r in page], limit, offset, total)


@bp.route("/admissions/<aid>/bind-guest", methods=["POST"])
def bind_guest(aid):
    _, role = authenticate()
    require_role(role, {"Guest", "GateAgent"})
    adm = get_admission(aid)
    body = get_json_body()
    if "guest_id" not in body or body["guest_id"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Missing required field: guest_id")
    guest = get_guest(body["guest_id"])
    adm["guest_id"] = guest["id"]
    touch(adm)
    return success(serialize.admission(adm))


@bp.route("/admissions/<aid>/assign-window", methods=["POST"])
def assign_window(aid):
    user_id, role = authenticate()
    require_role(role, {"Guest"})
    adm = get_admission(aid)
    require_owner(role, user_id, _owner_guest_id(adm))

    body = get_json_body()
    # Existence (priority 4): resolve entry_window_id from body.
    if "entry_window_id" not in body or body["entry_window_id"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Missing required field: entry_window_id")
    win = get_entry_window(body["entry_window_id"])
    # Schema (priority 5): expected_entry_window_version is mandatory.
    expected_version = require_int(body, "expected_entry_window_version")

    # State (priority 6): admission must be ISSUED.
    if adm["status"] != "ISSUED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "assign-window requires admission status ISSUED")

    # OCC (priority 7) precedes the remaining business checks.
    if expected_version != win["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412,
                       "expected_entry_window_version does not match window version")

    # Business: order FULFILLED, window OPEN, capacity (PRD §3.4 order).
    order = _order_of(adm)
    if order is None or order["fulfillment_status"] != "FULFILLED":
        raise ApiError(errors.ERR_ORDER_NOT_PAID, 409,
                       "assign-window requires the parent order to be FULFILLED")
    if win["status"] != "OPEN":
        raise ApiError(errors.ERR_WINDOW_NOT_OPEN, 409,
                       "assign-window requires window status OPEN")
    if win["reserved_count"] + win["admitted_count"] >= win["window_capacity"]:
        raise ApiError(errors.ERR_WINDOW_CAPACITY_EXCEEDED, 409,
                       "window capacity would be exceeded")

    adm["entry_window_id"] = win["id"]
    adm["status"] = "CONFIRMED"
    touch(adm)
    win["reserved_count"] += 1
    touch(win)
    return success(serialize.admission(adm))


@bp.route("/admissions/<aid>/check-in", methods=["POST"])
def check_in(aid):
    _, role = authenticate()
    require_role(role, {"GateAgent"})
    adm = get_admission(aid)

    # State (priority 6): admission must be CONFIRMED.
    if adm["status"] != "CONFIRMED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "check-in requires admission status CONFIRMED")

    win = db.entry_windows.get(adm["entry_window_id"])
    # Window must be OPEN (PRD §3.4).
    if win is None or win["status"] != "OPEN":
        raise ApiError(errors.ERR_WINDOW_NOT_OPEN, 409,
                       "check-in requires window status OPEN")
    # Bound guest required (ERR_GUEST_NOT_BOUND, priority 8).
    if not adm["guest_id"]:
        raise ApiError(errors.ERR_GUEST_NOT_BOUND, 409,
                       "check-in requires a bound guest_id")
    # Temporal: clock within [starts_at, ends_at) (priority 9).
    current = db.clock["current_utc"]
    if current is None:
        raise ApiError(errors.ERR_WINDOW_TIME_VIOLATION, 409,
                       "logical clock not set; check-in outside window interval")
    now_dt = parse_datetime(current, "current_utc")
    starts_dt = parse_datetime(win["starts_at"], "starts_at")
    ends_dt = parse_datetime(win["ends_at"], "ends_at")
    if not (starts_dt <= now_dt < ends_dt):
        raise ApiError(errors.ERR_WINDOW_TIME_VIOLATION, 409,
                       "check-in clock outside [starts_at, ends_at)")

    guest = db.guests[adm["guest_id"]]
    adm["band_color"] = band_color(guest["height_cm"])
    adm["status"] = "CHECKED_IN"
    touch(adm)
    win["reserved_count"] -= 1
    win["admitted_count"] += 1
    touch(win)
    return success(serialize.admission(adm))


@bp.route("/admissions/<aid>/freeze", methods=["POST"])
def freeze(aid):
    user_id, role = authenticate()
    require_role(role, {"Guest"})
    adm = get_admission(aid)
    require_owner(role, user_id, _owner_guest_id(adm))

    # State (priority 6): must be CONFIRMED.
    if adm["status"] != "CONFIRMED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "freeze requires admission status CONFIRMED")
    # SEASON_PASS only (ERR_FREEZE_NOT_ALLOWED, priority 11).
    if adm["product_type"] != "SEASON_PASS":
        raise ApiError(errors.ERR_FREEZE_NOT_ALLOWED, 409,
                       "freeze is only allowed for SEASON_PASS admissions")
    # Cap evaluated against running total before this episode (ERR_FREEZE_LIMIT_REACHED, priority 12).
    if adm["freeze_days_used"] >= MAX_FREEZE_DAYS:
        raise ApiError(errors.ERR_FREEZE_LIMIT_REACHED, 409,
                       "freeze_days_used already at or beyond the limit")

    adm["frozen_at"] = db.clock["current_utc"]
    adm["status"] = "FROZEN"
    touch(adm)
    win = db.entry_windows.get(adm["entry_window_id"])
    if win is not None and win["reserved_count"] > 0:
        win["reserved_count"] -= 1
        touch(win)
    return success(serialize.admission(adm))


@bp.route("/admissions/<aid>/unfreeze", methods=["POST"])
def unfreeze(aid):
    user_id, role = authenticate()
    require_role(role, {"Guest"})
    adm = get_admission(aid)
    require_owner(role, user_id, _owner_guest_id(adm))

    # State (priority 6): must be FROZEN.
    if adm["status"] != "FROZEN":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "unfreeze requires admission status FROZEN")
    # SEASON_PASS only (ERR_FREEZE_NOT_ALLOWED, priority 11).
    if adm["product_type"] != "SEASON_PASS":
        raise ApiError(errors.ERR_FREEZE_NOT_ALLOWED, 409,
                       "unfreeze is only allowed for SEASON_PASS admissions")

    win = db.entry_windows.get(adm["entry_window_id"])
    # Window must be OPEN or RESTRICTED (PRD §3.5).
    if win is None or win["status"] not in {"OPEN", "RESTRICTED"}:
        raise ApiError(errors.ERR_WINDOW_NOT_OPEN, 409,
                       "unfreeze requires window status OPEN or RESTRICTED")
    # Capacity (ERR_WINDOW_CAPACITY_EXCEEDED, priority 15).
    if win["reserved_count"] + win["admitted_count"] >= win["window_capacity"]:
        raise ApiError(errors.ERR_WINDOW_CAPACITY_EXCEEDED, 409,
                       "window capacity would be exceeded")

    # freeze_days_accounting: add this episode's ceil-days to the running total.
    frozen_at_dt = parse_datetime(adm["frozen_at"], "frozen_at")
    current = db.clock["current_utc"]
    current_dt = parse_datetime(current, "current_utc") if current else frozen_at_dt
    episode_days = freeze_episode_days(frozen_at_dt, current_dt)
    adm["freeze_days_used"] += episode_days
    adm["frozen_at"] = None
    adm["status"] = "CONFIRMED"
    touch(adm)
    win["reserved_count"] += 1
    touch(win)
    return success(serialize.admission(adm))


@bp.route("/admissions/<aid>/cancel", methods=["POST"])
def cancel_admission(aid):
    user_id, role = authenticate()
    require_role(role, {"Guest", "ParkManager"})
    adm = get_admission(aid)
    require_owner(role, user_id, _owner_guest_id(adm))

    if adm["status"] not in {"ISSUED", "CONFIRMED", "FROZEN"}:
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "cancel requires admission status ISSUED, CONFIRMED, or FROZEN")
    was_confirmed = adm["status"] == "CONFIRMED"
    adm["status"] = "CANCELLED"
    touch(adm)
    if was_confirmed:
        win = db.entry_windows.get(adm["entry_window_id"])
        if win is not None and win["reserved_count"] > 0:
            win["reserved_count"] -= 1
            touch(win)
    return success(serialize.admission(adm))
