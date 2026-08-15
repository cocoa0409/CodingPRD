"""BillingCyclePeriod endpoints."""
from flask import Blueprint, request

from db import db, stamp_new, touch, now_dt
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE_TRANSITION, ERR_WINDOW_DATE_ORDER,
    ERR_READ_WINDOW_NOT_OPEN, ERR_READ_WINDOW_STILL_OPEN,
    ERR_CYCLE_HAS_UNRESOLVED_STOPS, ERR_ACCOUNT_MISSING_BILLABLE_READ,
)
from middleware import require_roles, ALL_ROLES, body, req_str, req_date
from response import success, list_response, created_sorted
from serializers import ser_period, period_unresolved_stop_count, read_is_billable
from util import parse_date, parse_dt as _parse_dt


def parse_dt_date(s):
    return _parse_dt(s).date()

bp = Blueprint("periods", __name__)


def get_period(pid):
    p = db.periods.get(pid)
    if not p:
        raise ApiError(ERR_NOT_FOUND, "BillingCyclePeriod not found", 404)
    return p


@bp.route("/billing-cycle-periods", methods=["POST"])
def create():
    require_roles("MeterOpsAdmin")
    data = body()
    cycle_code = req_str(data, "cycle_code")
    period_start = req_date(data, "period_start_date")
    period_end = req_date(data, "period_end_date")
    window_open = req_date(data, "read_window_open_date")
    window_close = req_date(data, "read_window_close_date")
    bill_run = req_date(data, "bill_run_date")
    chain = [
        parse_date(period_start), parse_date(window_open), parse_date(window_close),
        parse_date(period_end), parse_date(bill_run),
    ]
    if any(chain[i] > chain[i + 1] for i in range(len(chain) - 1)):
        raise ApiError(
            ERR_WINDOW_DATE_ORDER,
            "Dates must satisfy period_start <= window_open <= window_close "
            "<= period_end <= bill_run_date",
            422,
        )
    rec = {
        "cycle_code": cycle_code,
        "period_start_date": period_start,
        "period_end_date": period_end,
        "read_window_open_date": window_open,
        "read_window_close_date": window_close,
        "bill_run_date": bill_run,
        "period_status": "SCHEDULED",
    }
    stamp_new(rec)
    db.periods[rec["id"]] = rec
    return success(ser_period(rec), code=201)


@bp.route("/billing-cycle-periods", methods=["GET"])
def list_all():
    require_roles(*ALL_ROLES)
    items = list(db.periods.values())
    for param in ("cycle_code", "period_status"):
        val = request.args.get(param)
        if val is not None:
            items = [p for p in items if p[param] == val]
    return list_response([ser_period(p) for p in created_sorted(items)])


@bp.route("/billing-cycle-periods/<pid>", methods=["GET"])
def get_one(pid):
    require_roles(*ALL_ROLES)
    return success(ser_period(get_period(pid)), code=200)


@bp.route("/billing-cycle-periods/<pid>/open-read-window", methods=["POST"])
def open_window(pid):
    require_roles("BillingLiaison", "MeterOpsAdmin")
    p = get_period(pid)
    if p["period_status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Period is not SCHEDULED", 409)
    if now_dt().date() < parse_date(p["read_window_open_date"]):
        raise ApiError(
            ERR_READ_WINDOW_NOT_OPEN,
            "Current date is before the read window open date",
            409,
        )
    p["period_status"] = "WINDOW_OPEN"
    touch(p)
    return success(ser_period(p), code=200)


@bp.route("/billing-cycle-periods/<pid>/close-read-window", methods=["POST"])
def close_window(pid):
    require_roles("BillingLiaison", "MeterOpsAdmin")
    p = get_period(pid)
    if p["period_status"] != "WINDOW_OPEN":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Period is not WINDOW_OPEN", 409)
    if now_dt().date() <= parse_date(p["read_window_close_date"]):
        raise ApiError(
            ERR_READ_WINDOW_STILL_OPEN,
            "Current date has not passed the read window close date",
            409,
        )
    p["period_status"] = "WINDOW_CLOSED"
    touch(p)
    for stop in db.stops.values():
        if stop["billing_cycle_period_id"] == pid and stop["stop_status"] == "PENDING":
            stop["stop_status"] = "NO_READ_PENDING"
            stop["no_read_reason"] = "WINDOW_EXPIRED"
            touch(stop)
    return success(ser_period(p), code=200)


def _account_has_billable_read(account_id, period):
    pid = period["id"]
    for r in db.reads.values():
        if r["service_account_id"] != account_id or not read_is_billable(r):
            continue
        stop = db.stops.get(r.get("route_stop_id") or "")
        if stop and stop["billing_cycle_period_id"] == pid:
            return True
        if r["read_source"] == "AMI_REMOTE" and r["route_stop_id"] is None:
            d = parse_dt_date(r["read_at"])
            if parse_date(period["read_window_open_date"]) <= d <= parse_date(
                period["read_window_close_date"]
            ):
                return True
    return False


@bp.route("/billing-cycle-periods/<pid>/finalize-billing", methods=["POST"])
def finalize_billing(pid):
    require_roles("BillingLiaison")
    p = get_period(pid)
    if p["period_status"] != "WINDOW_CLOSED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Period is not WINDOW_CLOSED", 409)
    if period_unresolved_stop_count(pid) != 0:
        raise ApiError(
            ERR_CYCLE_HAS_UNRESOLVED_STOPS,
            "Period still has stops in PENDING or NO_READ_PENDING",
            409,
        )
    for account in db.accounts.values():
        if account["billing_cycle_code"] != p["cycle_code"]:
            continue
        if account["account_status"] != "ACTIVE":
            continue
        if not _account_has_billable_read(account["id"], p):
            raise ApiError(
                ERR_ACCOUNT_MISSING_BILLABLE_READ,
                "An ACTIVE account in this cycle lacks a billable read for the period",
                409,
            )
    p["period_status"] = "BILLED"
    touch(p)
    return success(ser_period(p), code=200)


@bp.route("/billing-cycle-periods/<pid>/close", methods=["POST"])
def close_period(pid):
    require_roles("BillingLiaison")
    p = get_period(pid)
    if p["period_status"] != "BILLED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Period is not BILLED", 409)
    p["period_status"] = "CLOSED"
    touch(p)
    return success(ser_period(p), code=200)
