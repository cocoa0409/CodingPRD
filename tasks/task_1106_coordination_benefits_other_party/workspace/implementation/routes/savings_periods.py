"""Savings period endpoints."""

from flask import Blueprint, request

from db import stores, now_dt, parse_date
from errors import raise_err, ERR_INVALID_STATE, ERR_PERIOD_NOT_ENDED
from helpers import base_record, touch, get_or_404, body, req_str, paginate
from middleware import require_roles
from response import success
from services.calculations import savings_period_aggregation

bp = Blueprint("savings_periods", __name__)


@bp.route("/cob/savings-periods", methods=["POST"])
def create_period():
    require_roles("COBAuditor")
    data = body()
    start = req_str(data, "period_start_date")
    end = req_str(data, "period_end_date")
    rec = base_record()
    rec.update({
        "period_start_date": start,
        "period_end_date": end,
        "total_avoided_cents": 0,
        "total_recovered_cents": 0,
        "total_claims_adjusted": 0,
        "posture": "OPEN",
    })
    stores["savings_periods"][rec["id"]] = rec
    return success(rec, status=201)


@bp.route("/cob/savings-periods/<pid>", methods=["GET"])
def get_period(pid):
    require_roles("PlatformAdmin", "COBAuditor", "COBAnalyst")
    rec = get_or_404(stores["savings_periods"], pid, "savings period")
    return success(rec)


@bp.route("/cob/savings-periods", methods=["GET"])
def list_periods():
    require_roles("PlatformAdmin", "COBAuditor", "COBAnalyst")
    posture = request.args.get("posture")
    items = list(stores["savings_periods"].values())
    if posture:
        items = [p for p in items if p.get("posture") == posture]
    return paginate(items)


@bp.route("/cob/savings-periods/<pid>/close", methods=["POST"])
def close_period(pid):
    require_roles("COBAuditor")
    rec = get_or_404(stores["savings_periods"], pid, "savings period")
    if rec.get("posture") != "OPEN":
        raise_err(ERR_INVALID_STATE, "Savings period is not OPEN")
    if now_dt().date() <= parse_date(rec["period_end_date"]):
        raise_err(ERR_PERIOD_NOT_ENDED, "COBSavingsPeriod close requires current clock > period_end_date")
    totals = savings_period_aggregation(rec)
    rec.update(totals)
    rec["posture"] = "CLOSED"
    touch(rec)
    return success(rec)
