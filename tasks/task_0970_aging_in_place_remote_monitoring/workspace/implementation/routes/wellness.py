"""Check-ins and wellness reports."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from middleware import (require_roles, get_body, req_str, req_int, req_enum,
                        req_dt, opt_str, query_enum, check_senior_scope,
                        scoped_list, CHECKIN_KINDS, REPORT_MODES)
from response import ok, list_ok
from services import (create_record, touch, ser, current_subscription,
                      compute_report_metrics)

bp = Blueprint("wellness", __name__)


# -------------------------------------------------------------- check-ins --

@bp.post("/v1/check-ins")
def create_checkin():
    role, uid = require_roles(["Caregiver", "Senior"])
    b = get_body()
    senior_id = req_str(b, "senior_id")
    kind = req_enum(b, "kind", CHECKIN_KINDS)
    note = opt_str(b, "note")
    if senior_id not in db.seniors:
        raise errors.not_found("Senior not found")
    check_senior_scope(role, uid, senior_id)
    sub = current_subscription(senior_id)
    if sub is None or sub["service_status"] != "ACTIVE":
        raise errors.subscription_not_active()
    rec = create_record(db.checkins, {
        "senior_id": senior_id,
        "caregiver_id": uid if role == "Caregiver" else None,
        "kind": kind,
        "note": note,
        "occurred_at": db.clock,
    }, light=True)
    return ok(ser(rec), 201)


@bp.get("/v1/check-ins/<checkin_id>")
def get_checkin(checkin_id):
    role, uid = require_roles(["PlatformAdmin", "MonitoringAgent", "Caregiver", "Senior"])
    c = db.checkins.get(checkin_id)
    if c is None:
        raise errors.not_found("Check-in not found")
    check_senior_scope(role, uid, c["senior_id"])
    return ok(ser(c))


@bp.get("/v1/check-ins")
def list_checkins():
    role, uid = require_roles(["PlatformAdmin", "MonitoringAgent", "Caregiver", "Senior"])
    recs = list(db.checkins.values())
    recs = scoped_list(role, uid, recs, request.args.get("senior_id"))
    cid = request.args.get("caregiver_id")
    if cid is not None:
        recs = [r for r in recs if r.get("caregiver_id") == cid]
    return list_ok(recs, ser)


# -------------------------------------------------------- wellness reports -

@bp.post("/v1/wellness-reports")
def create_report():
    require_roles(["PlatformAdmin", "MonitoringAgent"])
    b = get_body()
    senior_id = req_str(b, "senior_id")
    period_start = req_dt(b, "period_start")
    period_end = req_dt(b, "period_end")
    mode = req_enum(b, "mode", REPORT_MODES)
    # body-level shape checks: midnight-aligned start, span 1..31 days
    if (period_start.hour, period_start.minute, period_start.second,
            period_start.microsecond) != (0, 0, 0, 0):
        raise errors.invalid_request("period_start must be aligned to midnight UTC")
    span_seconds = (period_end - period_start).total_seconds()
    if span_seconds < 86400 or span_seconds > 31 * 86400:
        raise errors.invalid_request("Report period must span between 1 and 31 days")
    if senior_id not in db.seniors:
        raise errors.not_found("Senior not found")
    # pinned gate order: subscription -> duplicate -> temporal -> feature
    sub = current_subscription(senior_id)
    if sub is None or sub["service_status"] != "ACTIVE":
        raise errors.subscription_not_active()
    if mode == "FINAL":
        for r in db.reports.values():
            if (r["senior_id"] == senior_id and r["mode"] == "FINAL"
                    and period_start < r["period_end"] and r["period_start"] < period_end):
                raise errors.duplicate_report()
    now = db.clock
    if mode == "FINAL":
        if not now > period_end:
            raise errors.period_not_closed()
    else:
        if not (period_start <= now <= period_end):
            raise errors.period_not_closed()
    plan = db.plans.get(sub["plan_id"])
    if plan is None or not plan["wellness_report_enabled"]:
        raise errors.feature_gated()
    metrics = compute_report_metrics(senior_id, period_start, period_end, mode)
    rec = create_record(db.reports, {
        "senior_id": senior_id,
        "period_start": period_start,
        "period_end": period_end,
        "mode": mode,
        "status": "READY",
        **metrics,
    })
    return ok(ser(rec), 201)


def _get_report(report_id):
    r = db.reports.get(report_id)
    if r is None:
        raise errors.not_found("Wellness report not found")
    return r


@bp.get("/v1/wellness-reports/<report_id>")
def get_report(report_id):
    role, uid = require_roles(["PlatformAdmin", "MonitoringAgent", "Caregiver"])
    r = _get_report(report_id)
    check_senior_scope(role, uid, r["senior_id"])
    return ok(ser(r))


@bp.get("/v1/wellness-reports")
def list_reports():
    role, uid = require_roles(["PlatformAdmin", "MonitoringAgent", "Caregiver"])
    recs = list(db.reports.values())
    recs = scoped_list(role, uid, recs, request.args.get("senior_id"))
    m = query_enum("mode", REPORT_MODES)
    if m is not None:
        recs = [r for r in recs if r["mode"] == m]
    return list_ok(recs, ser)


@bp.post("/v1/wellness-reports/<report_id>/regenerate")
def regenerate_report(report_id):
    require_roles(["PlatformAdmin"])
    b = get_body()
    expected_version = req_int(b, "expected_report_version")
    r = _get_report(report_id)
    if r["status"] != "READY":
        raise errors.invalid_state("Report is not READY")
    if expected_version != r["version"]:
        raise errors.stale_version()
    metrics = compute_report_metrics(r["senior_id"], r["period_start"],
                                     r["period_end"], r["mode"])
    r.update(metrics)
    touch(r)
    return ok(ser(r))


@bp.post("/v1/wellness-reports/<report_id>/deliver")
def deliver_report(report_id):
    require_roles(["PlatformAdmin", "MonitoringAgent"])
    r = _get_report(report_id)
    if r["status"] != "READY":
        raise errors.invalid_state("Report is not READY")
    r["status"] = "DELIVERED"
    touch(r)
    return ok(ser(r))
