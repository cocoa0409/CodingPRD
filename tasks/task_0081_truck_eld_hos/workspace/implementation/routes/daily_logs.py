"""DailyLog endpoints + certification lifecycle (PRD §3.8)."""
from datetime import timezone, timedelta

from flask import Blueprint, request

import clock
import db
import errors
import model
import response
import serializers as ser
import timeutil
import validation as val
from middleware import get_auth, require_role
from paginate import paginate
from services import hos

bp = Blueprint("daily_logs", __name__)

CERT_STATUSES = {"UNCERTIFIED", "CERTIFIED", "RECERTIFY_REQUIRED"}


@bp.route("/eld/daily-logs", methods=["POST"])
def open_log():
    _, role = get_auth()
    require_role(role, {"Driver", "CarrierAdmin"})
    body = val.get_body()
    driver_id = val.require_str(body, "driver_id")
    log_date = val.require_str(body, "log_date")
    if not timeutil.is_date_str(log_date):
        raise errors.err(errors.ERR_INVALID_REQUEST, "log_date must be YYYY-MM-DD.")

    driver = db.drivers.get(driver_id)
    if driver is None:
        raise errors.err(errors.ERR_REFERENCE_NOT_FOUND, "driver_id not found.")

    d, on, off = hos.compute_log_totals(driver, log_date)
    rec = {
        "driver_id": driver_id,
        "log_date": log_date,
        "total_driving_minutes": d,
        "total_on_duty_minutes": on,
        "total_off_duty_minutes": off,
        "certification_status": "UNCERTIFIED",
        "certified_at": None,
    }
    model.stamp_new(rec)
    db.daily_logs[rec["id"]] = rec
    return response.object_response(ser.daily_log_view(rec), 201)


@bp.route("/eld/daily-logs/<id>", methods=["GET"])
def get_log(id):
    _, role = get_auth()
    require_role(role, {"Driver", "CarrierAdmin", "SafetyOfficer"})
    rec = db.daily_logs.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Daily log not found.")
    return response.object_response(ser.daily_log_view(rec), 200)


@bp.route("/eld/daily-logs", methods=["GET"])
def list_logs():
    _, role = get_auth()
    require_role(role, {"Driver", "CarrierAdmin", "SafetyOfficer"})
    limit, offset = val.get_pagination()
    items = list(db.daily_logs.values())
    driver_id = request.args.get("driver_id")
    cert_status = request.args.get("certification_status")
    log_date = request.args.get("log_date")
    if driver_id is not None:
        items = [r for r in items if r["driver_id"] == driver_id]
    if cert_status is not None:
        items = [r for r in items if r["certification_status"] == cert_status]
    if log_date is not None:
        items = [r for r in items if r["log_date"] == log_date]
    page, total = paginate(items, limit, offset)
    return response.array_response([ser.daily_log_view(r) for r in page], limit, offset, total)


def _today_home_terminal(driver):
    return timeutil.home_terminal_date(clock.now(), driver["home_terminal_tz_offset_minutes"])


@bp.route("/eld/daily-logs/<id>/certify", methods=["POST"])
def certify_log(id):
    user_id, role = get_auth()
    require_role(role, {"Driver"})
    rec = db.daily_logs.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Daily log not found.")

    # ownership
    if user_id != rec["driver_id"]:
        raise errors.err(errors.ERR_UNAUTHORIZED, "Only the owning driver may certify.")

    # state: transition defined only from UNCERTIFIED or RECERTIFY_REQUIRED
    if rec["certification_status"] not in ("UNCERTIFIED", "RECERTIFY_REQUIRED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Log is not in a certifiable state.")

    driver = db.drivers.get(rec["driver_id"])
    today = _today_home_terminal(driver)
    today_ord = timeutil.date_to_ordinal(today)
    log_ord = timeutil.date_to_ordinal(rec["log_date"])

    # future check
    if log_ord > today_ord:
        raise errors.err(errors.ERR_CANNOT_CERTIFY_FUTURE, "Cannot certify a future log.")

    # closed-day open-event check (log_date < today)
    if log_ord < today_ord:
        tz = driver["home_terminal_tz_offset_minutes"]
        for e in db.duty_events.values():
            if (e["driver_id"] == rec["driver_id"] and e["record_status"] == "ACTIVE"
                    and e["duration_minutes"] is None):
                day = timeutil.home_terminal_date(e["_event_dt"], tz)
                if day == rec["log_date"]:
                    raise errors.err(errors.ERR_OPEN_EVENT_ON_CLOSED_DAY,
                                     "Open event on a closed day blocks certification.")

    rec["certification_status"] = "CERTIFIED"
    rec["certified_at"] = timeutil.iso_now_str(clock.now())
    model.touch(rec)
    return response.object_response(ser.daily_log_view(rec), 200)
