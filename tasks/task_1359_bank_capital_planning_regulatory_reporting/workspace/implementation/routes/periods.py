"""ReportingPeriod endpoints."""

from __future__ import annotations

from flask import Blueprint

from db import reporting_periods, stamp_new, touch
from errors import raise_err, ERR_INVALID_STATE_TRANSITION, ERR_TEMPORAL_VIOLATION
from middleware import require_roles
from response import success_object, success_list
from services.core import (
    ser_period, get_bank, get_period, compute_filing_due_at, PERIOD_QUARTERS,
)
from util import get_body, req_date, req_int, req_enum, apply_filters, sorted_page, day_after

bp = Blueprint("periods", __name__)


@bp.route("/banks/<bankId>/reporting-periods", methods=["POST"])
@require_roles("CapitalAnalyst")
def create_period(bankId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    body = get_body()
    period_end = req_date(body, "period_end_date")
    period_year = req_int(body, "period_year")
    quarter = req_enum(body, "period_quarter", PERIOD_QUARTERS)
    due_dt = compute_filing_due_at(period_end, quarter)
    period = {
        "bank_id": bank["id"],
        "period_end_date": period_end.isoformat(),
        "period_year": period_year,
        "period_quarter": quarter,
        "late_filing": False,
        "status": "OPEN",
        "_period_end": period_end,
        "_period_end_boundary": day_after(period_end),
        "_filing_due_dt": due_dt,
    }
    stamp_new(period)
    reporting_periods[period["id"]] = period
    return success_object(ser_period(period), 201)


@bp.route("/banks/<bankId>/reporting-periods/<periodId>", methods=["GET"])
@require_roles("Any")
def get_one_period(bankId: str, periodId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    return success_object(ser_period(get_period(bank, periodId)))


@bp.route("/banks/<bankId>/reporting-periods", methods=["GET"])
@require_roles("Any")
def list_periods(bankId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    items = [p for p in reporting_periods.values() if p["bank_id"] == bank["id"]]
    items = apply_filters(items, {"status": "status", "period_year": "period_year"})
    page, limit, offset, total = sorted_page(items)
    return success_list([ser_period(p) for p in page], limit, offset, total)


@bp.route("/banks/<bankId>/reporting-periods/<periodId>/close", methods=["POST"])
@require_roles("CapitalAnalyst")
def close_period(bankId: str, periodId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    period = get_period(bank, periodId)
    if period["status"] not in ("ACCEPTED", "RE_ACCEPTED"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "ReportingPeriod must be ACCEPTED or RE_ACCEPTED to close")
    # Periods must close in chronological order.
    for other in reporting_periods.values():
        if (other["bank_id"] == bank["id"] and other["id"] != period["id"]
                and other["status"] != "CLOSED"
                and other["_period_end"] < period["_period_end"]):
            raise_err(ERR_TEMPORAL_VIOLATION,
                      "Earlier-dated ReportingPeriod for this bank is not CLOSED")
    period["status"] = "CLOSED"
    touch(period)
    return success_object(ser_period(period))
