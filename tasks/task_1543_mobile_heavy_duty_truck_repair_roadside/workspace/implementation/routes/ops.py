"""Logical clock and daily operations run."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, touch
from errors import ApiError
from middleware import auth
from response import success
from services.cascades import (maybe_reinstate_credit_hold,
                               revert_call_if_no_active_dispatch, wall_now)
from util import fmt_dt, validate_body, Field

bp = Blueprint("ops", __name__)

ESTIMATE_EXPIRY_DAYS = 7


@bp.route("/roadside/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(["OpsAdmin"])
    body = request.get_json(silent=True)
    vals = validate_body(body, [Field("to_iso8601", "datetime", required=True)])
    target = vals["to_iso8601"]
    if target < store.clock:
        raise ApiError("ERR_CLOCK_REGRESSION",
                       "The logical clock may only move forward", 422)
    store.clock = target
    return success({"current_utc": fmt_dt(store.clock)})


@bp.route("/roadside/_ops/run_daily", methods=["POST"])
def run_daily():
    auth(["OpsAdmin"])
    now = store.clock
    expired_dispatch_count = 0
    expired_estimate_count = 0
    escalated_defect_count = 0
    reinstated_fleet_count = 0

    # expire stale PROPOSED dispatches (window_end_at < now)
    for disp in list(store.dispatches.values()):
        if disp["status"] == "PROPOSED" and disp["window_end_at"] < now:
            disp["status"] = "EXPIRED"
            touch(disp, wall_now())
            expired_dispatch_count += 1
            call = store.service_calls.get(disp["service_call_id"])
            if call is not None:
                revert_call_if_no_active_dispatch(call)

    # expire stale SUBMITTED estimates (now > submitted_at + 7 days)
    for est in list(store.estimates.values()):
        if (est["status"] == "SUBMITTED" and est["submitted_at"] is not None
                and now > est["submitted_at"] + timedelta(days=ESTIMATE_EXPIRY_DAYS)):
            est["status"] = "EXPIRED"
            touch(est, wall_now())
            expired_estimate_count += 1

    # escalate overdue defects (strictly past deadline)
    for defect in list(store.inspection_defects.values()):
        if (defect["status"] in ("OPEN", "REPAIR_SCHEDULED", "CORRECTED",
                                 "VERIFICATION_FAILED")
                and now > defect["correction_deadline_at"]):
            defect["status"] = "ESCALATED"
            defect["escalation_count"] = defect.get("escalation_count", 0) + 1
            touch(defect, wall_now())
            escalated_defect_count += 1

    # reinstate CREDIT_HOLD fleets back within cap (incl. month rollover)
    for fleet in list(store.fleets.values()):
        if (fleet["status"] == "SUSPENDED"
                and fleet["suspension_reason"] == "CREDIT_HOLD"):
            if maybe_reinstate_credit_hold(fleet):
                reinstated_fleet_count += 1

    return success({
        "expired_dispatch_count": expired_dispatch_count,
        "expired_estimate_count": expired_estimate_count,
        "escalated_defect_count": escalated_defect_count,
        "reinstated_fleet_count": reinstated_fleet_count,
    })
