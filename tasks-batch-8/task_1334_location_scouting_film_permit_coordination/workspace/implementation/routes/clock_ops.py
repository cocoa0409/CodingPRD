"""Logical clock and ops sweep endpoints."""

from flask import Blueprint, request
from middleware import require_role
from response import success_object, error_response
from errors import ApiError, ERR_INVALID_REQUEST
from db import store
from services.helpers import parse_datetime, touch, parse_date
from datetime import datetime, timezone, timedelta

bp = Blueprint("clock_ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = require_role("FilmOffice")
    payload = request.get_json(silent=True) or {}
    to_iso = payload.get("to_iso8601")
    if not to_iso or not isinstance(to_iso, str):
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 is required", 400)
    dt = parse_datetime(to_iso, "to_iso8601")
    store.clock.set(dt)
    return success_object({"now": store.clock.now_iso()})


@bp.route("/_ops/sweep", methods=["POST"])
def ops_sweep():
    user_id, role = require_role("FilmOffice")
    now = store.clock.now()
    today = now.date() if hasattr(now, 'date') else now
    swept = 0

    # 1. Expire ISSUED permits past shoot_end_date with no IN_PROGRESS shoot day
    for pa in list(store.permit_applications.values()):
        if pa["status"] == "ISSUED":
            end_date = parse_date(pa["shoot_end_date"])
            if today > end_date:
                # Check if any shoot day under it reached IN_PROGRESS (or beyond: COMPLETED, SHUT_DOWN)
                has_progress = any(
                    sd.get("permit_application_id") == pa["id"]
                    and sd["status"] in ("IN_PROGRESS", "COMPLETED", "SHUT_DOWN")
                    for sd in store.shoot_days.values()
                )
                if not has_progress:
                    pa["status"] = "EXPIRED"
                    touch(pa)
                    swept += 1
                    # Cancel REQUESTED/APPROVED street closures
                    for sc in store.street_closures.values():
                        if sc.get("permit_application_id") == pa["id"] and sc["status"] in ("REQUESTED", "APPROVED"):
                            sc["status"] = "CANCELLED"
                            touch(sc)
                            swept += 1

    # 2. Lapse VERIFIED certs past expiry_date
    for cert in list(store.insurance_certificates.values()):
        if cert["status"] == "VERIFIED":
            exp = parse_date(cert["expiry_date"])
            if today > exp:
                cert["status"] = "LAPSED"
                touch(cert)
                swept += 1

    # 3. Escalate OPEN complaints past response_due_at
    for c in list(store.complaints.values()):
        if c["status"] == "OPEN":
            due = parse_datetime(c["response_due_at"])
            if now > due:
                c["status"] = "ESCALATED"
                touch(c)
                swept += 1
                # CRITICAL cascade: shut down IN_PROGRESS day
                if c.get("severity") == "CRITICAL":
                    sd = store.shoot_days.get(c.get("shoot_day_id"))
                    if sd and sd["status"] == "IN_PROGRESS":
                        from services.helpers import shut_down_shoot_day
                        shut_down_shoot_day(sd)
                        swept += 1

    # 4. Street closure APPROVED -> ACTIVE -> COMPLETED
    for sc in list(store.street_closures.values()):
        if sc["status"] == "APPROVED":
            cs = parse_datetime(sc["closure_start"])
            if now >= cs:
                sc["status"] = "ACTIVE"
                touch(sc)
                swept += 1
        # Check ACTIVE -> COMPLETED (may apply to just-activated ones too)
        if sc["status"] == "ACTIVE":
            ce = parse_datetime(sc["closure_end"])
            if now >= ce:
                sc["status"] = "COMPLETED"
                touch(sc)
                swept += 1

    # 5. READY shoot days -> IN_PROGRESS on shoot_date
    for sd in list(store.shoot_days.values()):
        if sd["status"] == "READY":
            sd_date = parse_date(sd["shoot_date"])
            if today >= sd_date:
                sd["status"] = "IN_PROGRESS"
                touch(sd)
                swept += 1

    return success_object({"swept": swept})
