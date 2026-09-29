"""Service periods, performance reports, verification, invoicing and payment."""

from decimal import Decimal

from flask import Blueprint

import calc
from db import db, insert, public, setf, touch, whole_days
from errors import fail
from middleware import (ROLE_AUTHORITY_OFFICER, ROLE_CONCESSIONAIRE, actor, as_instant,
                        body, concession_of_period, get_concession, get_period,
                        get_report, owner_guard, period_of_report, req_instant, req_int,
                        req_str, require_auth)
from response import created, ok

bp = Blueprint("periods", __name__)


# ------------------------------------------------------------------ open a period
@bp.post("/ppp/concessions/<row_id>/service-periods")
def create_period(row_id):
    require_auth(ROLE_AUTHORITY_OFFICER)
    concession = get_concession(row_id)
    data = body()
    period_index = req_int(data, "period_index", minimum=1)
    raw_start, start_dt = req_instant(data, "period_start")
    raw_end, end_dt = req_instant(data, "period_end")
    if concession["status"] not in ("OPERATIONS", "STEP_IN"):
        fail("ERR_CONCESSION_STATE_FORBIDS_OPERATION")

    days = whole_days(start_dt, end_dt)
    if end_dt <= start_dt or days < 1:
        fail("ERR_INVALID_INTERVAL")

    for other in calc.concession_periods(concession["id"]):
        o_start = as_instant(other["period_start"])
        o_end = as_instant(other["period_end"])
        if start_dt.date() < o_end.date() and o_start.date() < end_dt.date():
            fail("ERR_SERVICE_PERIOD_OVERLAP")

    for other in calc.concession_periods(concession["id"]):
        if other["period_index"] == period_index:
            fail("ERR_DUPLICATE_PERIOD_INDEX")

    gross = concession["monthly_unitary_charge_cents"] or 0
    cap = calc.rhu(Decimal(gross) * Decimal(str(concession["deduction_cap_pct"])))
    row = insert("periods", {
        "concession_id": concession["id"],
        "period_index": period_index,
        "period_start": raw_start,
        "period_end": raw_end,
        "days_in_period": days,
        "reporting_status": "PENDING",
        "payment_status": "UNBILLED",
        "gross_unitary_charge_cents": gross,
        "deduction_cap_cents": cap,
        "unavailable_minutes_verified": None,
        "deduction_points_total": 0,
        "total_deduction_cents": 0,
        "relief_credit_cents": 0,
        "net_payment_cents": gross,
        "availability_ratio": None,
        "verified_at": None,
        "invoiced_at": None,
        "paid_at": None,
        "payment_reference": None,
    })
    return created(public(row))


# ------------------------------------------------------------------ self reporting
@bp.post("/ppp/service-periods/<row_id>/performance-reports")
def create_report(row_id):
    require_auth(ROLE_CONCESSIONAIRE)
    period = get_period(row_id)
    concession = concession_of_period(period)
    owner_guard(concession)
    data = body()
    minutes = req_int(data, "unavailable_minutes", minimum=0)
    cat_a = req_int(data, "category_a_failures", minimum=0)
    cat_b = req_int(data, "category_b_failures", minimum=0)
    expected = req_int(data, "expected_service_period_version", minimum=0)
    if expected != period["version"]:
        fail("ERR_STALE_SERVICE_PERIOD_VERSION")
    if period["reporting_status"] not in ("PENDING", "SELF_REPORTED"):
        fail("ERR_INVALID_STATE_TRANSITION")
    if concession["status"] != "OPERATIONS":
        fail("ERR_CONCESSION_STATE_FORBIDS_OPERATION")

    for incumbent in calc.period_reports(period["id"]):
        if incumbent["status"] == "SUBMITTED":
            setf(incumbent, "status", "SUPERSEDED")

    row = insert("reports", {
        "service_period_id": period["id"],
        "unavailable_minutes": minutes,
        "category_a_failures": cat_a,
        "category_b_failures": cat_b,
        "reported_points": calc.report_points(minutes, cat_a, cat_b),
        "status": "SUBMITTED",
        "variance_pct": None,
        "rejection_reason": None,
        "submitted_at": db.now_str(),
    })
    setf(period, "reporting_status", "SELF_REPORTED")
    touch(period)
    return created(public(row))


@bp.post("/ppp/performance-reports/<row_id>/reject")
def reject_report(row_id):
    require_auth(ROLE_AUTHORITY_OFFICER)
    report = get_report(row_id)
    period = period_of_report(report)
    data = body()
    reason = req_str(data, "rejection_reason", max_len=2000)
    if report["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if period["reporting_status"] != "SELF_REPORTED":
        fail("ERR_INVALID_STATE_TRANSITION")

    setf(report, "rejection_reason", reason)
    setf(report, "status", "REJECTED")
    remaining = [r for r in calc.period_reports(period["id"]) if r["status"] == "SUBMITTED"]
    if not remaining:
        setf(period, "reporting_status", "PENDING")
    touch(period)
    return ok(public(report))


# ------------------------------------------------------------------ verification
@bp.post("/ppp/service-periods/<row_id>/verify")
def verify_period(row_id):
    require_auth(ROLE_AUTHORITY_OFFICER)
    period = get_period(row_id)
    concession = concession_of_period(period)
    data = body()
    minutes = req_int(data, "verified_unavailable_minutes", minimum=0)
    cat_a = req_int(data, "verified_category_a_failures", minimum=0)
    cat_b = req_int(data, "verified_category_b_failures", minimum=0)

    if period["reporting_status"] != "SELF_REPORTED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if concession["status"] != "OPERATIONS":
        fail("ERR_CONCESSION_STATE_FORBIDS_OPERATION")
    submitted = [r for r in calc.period_reports(period["id"]) if r["status"] == "SUBMITTED"]
    if len(submitted) != 1:
        fail("ERR_INVALID_STATE_TRANSITION")
    for event in calc.period_events(period["id"]):
        if event["issued_by_user_id"] == actor():
            fail("ERR_SEGREGATION_OF_DUTIES")

    report = submitted[0]
    setf(period, "unavailable_minutes_verified", minutes)
    ratio = calc.availability_ratio(period["days_in_period"], minutes)
    setf(period, "availability_ratio", float(ratio) if ratio is not None else None)

    verified_points = calc.report_points(minutes, cat_a, cat_b)
    variance = calc.variance_pct(report["reported_points"], verified_points)
    setf(report, "variance_pct", float(variance))
    setf(report, "status", "VERIFIED")

    if variance > calc.SELF_REPORT_VARIANCE_TOLERANCE_PCT:
        points = calc.understatement_points(report["reported_points"], verified_points)
        if points > 0:
            calc.issue_deduction_event(period, "SELF_REPORT_UNDERSTATEMENT", points,
                                       "SYSTEM", report_id=report["id"])

    calc.price_period(period)
    projected = (concession["availability_deduction_ytd_cents"]
                 + period["total_deduction_cents"])
    calc.annual_cap_guard(concession, projected)

    setf(period, "reporting_status", "VERIFIED")
    setf(period, "verified_at", db.now_str())
    calc.recompute_ytd(concession)
    calc.recompute_points_and_breach(concession)
    return ok(public(period))


# ------------------------------------------------------------------ payment axis
@bp.post("/ppp/service-periods/<row_id>/invoice")
def invoice_period(row_id):
    require_auth(ROLE_CONCESSIONAIRE)
    period = get_period(row_id)
    concession = concession_of_period(period)
    owner_guard(concession)
    if period["payment_status"] != "UNBILLED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if period["reporting_status"] != "VERIFIED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if concession["status"] != "OPERATIONS":
        fail("ERR_CONCESSION_STATE_FORBIDS_OPERATION")
    setf(period, "invoiced_at", db.now_str())
    setf(period, "payment_status", "INVOICED")
    return ok(public(period))


@bp.post("/ppp/service-periods/<row_id>/pay")
def pay_period(row_id):
    require_auth(ROLE_AUTHORITY_OFFICER)
    period = get_period(row_id)
    concession = concession_of_period(period)
    data = body()
    reference = req_str(data, "payment_reference", max_len=200)
    if period["payment_status"] != "INVOICED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if concession["status"] != "OPERATIONS":
        fail("ERR_CONCESSION_STATE_FORBIDS_OPERATION")
    setf(period, "paid_at", db.now_str())
    setf(period, "payment_reference", reference)
    setf(period, "payment_status", "PAID")
    period["_total_deduction_at_paid"] = period["total_deduction_cents"]
    return ok(public(period))
