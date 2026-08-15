"""Checkpoint ops runs: DAILY_SWEEP and MONTHLY_BILLING (PRD §3.9)."""
from datetime import date, datetime

from flask import Blueprint, request

import clock
import store
from auth import authenticate, authorize
from errors import (
    ERR_INVALID_REQUEST,
    ERR_PERIOD_ALREADY_BILLED,
    ERR_PERIOD_NOT_CLOSED,
    raise_err,
)
from services import (
    OPS_KINDS,
    ops_run_out,
    run_daily_sweep,
    run_monthly_billing,
)
from util import body_json, get_or_404, list_response, opt_str, req_enum, success_object, valid_year_month

bp = Blueprint("ops_runs", __name__)

OPS_ROLES = ["BankOps"]
READ_ROLES = ["BankTreasuryManager", "BankOps"]


@bp.route("/treasury/ops-runs", methods=["POST"])
def create_ops_run():
    _, role, _user = authenticate()
    authorize(role, _user, OPS_ROLES)
    body = body_json()
    kind = req_enum(body, "kind", OPS_KINDS)
    enrollment_id = opt_str(body, "enrollment_id")
    period = opt_str(body, "period")
    if kind == "DAILY_SWEEP":
        if period is not None:
            raise_err(ERR_INVALID_REQUEST, "period must not be supplied for DAILY_SWEEP")
    else:  # MONTHLY_BILLING
        if enrollment_id is None:
            raise_err(ERR_INVALID_REQUEST, "enrollment_id is required for MONTHLY_BILLING")
        if period is None:
            raise_err(ERR_INVALID_REQUEST, "period is required for MONTHLY_BILLING")
        if not valid_year_month(period):
            raise_err(ERR_INVALID_REQUEST, "period must be YYYY-MM")

    if enrollment_id is not None:
        get_or_404(store.enrollments, enrollment_id, "TreasuryEnrollment")

    counters = {
        "exceptions_defaulted": 0,
        "checks_staled": 0,
        "ach_rules_expired": 0,
        "sessions_marked_no_show": 0,
        "fees_billed": 0,
        "adjustment_cents": 0,
        "minimum_topup_cents": 0,
    }
    if kind == "DAILY_SWEEP":
        counters.update(run_daily_sweep(enrollment_id))
    else:
        # state gate (p7) before temporal gate (p8)
        already_billed = any(
            f["enrollment_id"] == enrollment_id
            and f["period"] == period
            and f["status"] == "BILLED"
            for f in store.fees.values()
        )
        if already_billed:
            raise_err(ERR_PERIOD_ALREADY_BILLED, "Period already billed for this enrollment")
        year, month = int(period[:4]), int(period[5:7])
        next_month = date(year + (1 if month == 12 else 0), (month % 12) + 1, 1)
        period_close = datetime(next_month.year, next_month.month, next_month.day, tzinfo=clock.UTC)
        if clock.now() < period_close:
            raise_err(ERR_PERIOD_NOT_CLOSED, "Billing period has not fully elapsed")
        counters.update(run_monthly_billing(enrollment_id, period))

    rec = {
        "id": store.new_id(),
        "created_at": clock.now(),
        "_seq": store.next_seq(),
        "kind": kind,
        "enrollment_id": enrollment_id,
        "period": period if kind == "MONTHLY_BILLING" else None,
        "status": "COMPLETED",
    }
    rec.update(counters)
    store.ops_runs[rec["id"]] = rec
    return success_object(ops_run_out(rec), 201)


@bp.route("/treasury/ops-runs/<rid>", methods=["GET"])
def get_ops_run(rid):
    _, role, _user = authenticate()
    authorize(role, _user, READ_ROLES)
    rec = get_or_404(store.ops_runs, rid, "OpsRun")
    return success_object(ops_run_out(rec), 200)


@bp.route("/treasury/ops-runs", methods=["GET"])
def list_ops_runs():
    _, role, _user = authenticate()
    authorize(role, _user, READ_ROLES)
    records = list(store.ops_runs.values())
    enr = request.args.get("enrollment_id")
    if enr is not None:
        records = [r for r in records if r["enrollment_id"] == enr]
    kind = request.args.get("kind")
    if kind is not None:
        records = [r for r in records if r["kind"] == kind]
    return list_response(records, ops_run_out)
