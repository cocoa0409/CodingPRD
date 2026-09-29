"""AccrualPeriod routes: the contiguous provisional-accrual ledger."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import db
from errors import ApiError
from middleware import (COMPENSATION_COMMITTEE, FINANCE_CONTROLLER, PLAN_ADMIN,
                        authenticate, bad_request, get_body, opt_string,
                        query_param, req_date, req_id, req_percent, req_string)
from response import object_response
from routes.common import paginated
from serialize import accrual_out
from services import accrual, lookup, rollup

bp = Blueprint("accrual_periods", __name__)

READ_ROLES = [PLAN_ADMIN, FINANCE_CONTROLLER, COMPENSATION_COMMITTEE]
LIST_ROLES = [PLAN_ADMIN, FINANCE_CONTROLLER]


def _ordered_periods(plan_id):
    records = db.plan_periods(plan_id)
    records.sort(key=lambda r: (r["period_start"], r["created_at"], r["_seq"]))
    return records


@bp.route("/accrual-periods", methods=["POST"])
def create_accrual_period():
    authenticate([FINANCE_CONTROLLER])
    body = get_body()

    plan_id = req_id(body, "plan_id")
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    forecast = req_percent(body, "forecast_company_achievement_pct",
                           minimum=0, maximum=200)
    if period_end < period_start:
        raise bad_request("Field 'period_end' must be on or after 'period_start'")

    plan = lookup.plan(plan_id)

    if plan["status"] in ("PAID_OUT", "SETTLED"):
        raise ApiError("ERR_PLAN_ALREADY_SETTLED")

    existing = _ordered_periods(plan_id)
    for other in existing:
        if other["status"] == "REVERSED":
            continue
        other_start = db.as_date(other["period_start"])
        other_end = db.as_date(other["period_end"])
        if period_start <= other_end and other_start <= period_end:
            raise ApiError("ERR_ACCRUAL_PERIOD_OVERLAP")

    if not existing:
        expected_start = db.as_date(plan["plan_period_start"])
    else:
        expected_start = max(db.as_date(p["period_end"]) for p in existing) \
            + timedelta(days=1)
    if period_start != expected_start:
        raise ApiError("ERR_ACCRUAL_PERIOD_GAP",
                       "period_start must be %s" % expected_start.isoformat())

    period = db.base_record()
    period.update({
        "plan_id": plan_id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "forecast_company_achievement_pct": forecast,
        "status": "OPEN",
        "provisional_target_basis": None,
        "provisional_pool_cents": 0,
        "elapsed_days": 0,
        "cumulative_accrual_target_cents": 0,
        "period_accrual_cents": 0,
        "burden_rate_pct": Decimal("0.00"),
        "burden_cents": 0,
        "total_period_cents": 0,
        "posting_note": None,
        "reversal_reason": None,
    })
    db.accrual_periods[period["id"]] = period
    return object_response(accrual_out(period), 201)


@bp.route("/accrual-periods/<period_id>/post", methods=["POST"])
def post_accrual_period(period_id):
    authenticate([FINANCE_CONTROLLER])
    period = lookup.accrual_period(period_id)
    body = get_body()
    posting_note = opt_string(body, "posting_note")

    plan = lookup.plan(period["plan_id"])

    if period["status"] != "OPEN":
        raise ApiError("ERR_ACCRUAL_ALREADY_POSTED",
                       "Posting requires a period in OPEN")
    if plan["status"] in ("PAID_OUT", "SETTLED"):
        raise ApiError("ERR_PLAN_ALREADY_SETTLED")
    this_start = db.as_date(period["period_start"])
    for other in _ordered_periods(plan["id"]):
        if other["id"] == period["id"]:
            continue
        if db.as_date(other["period_end"]) < this_start \
                and other["status"] not in ("POSTED", "REVERSED"):
            raise ApiError("ERR_ACCRUAL_PERIOD_GAP",
                           "An earlier accrual period is still OPEN")

    accrual.value_period(plan, period)
    if posting_note is not None:
        period["posting_note"] = posting_note
    period["status"] = "POSTED"
    db.touch(period)

    plan_before = db.snapshot(plan)
    rollup.refresh_accrual_ledger(plan)
    db.bump_if_changed(plan, plan_before)
    return object_response(accrual_out(period))


@bp.route("/accrual-periods/<period_id>/reverse", methods=["POST"])
def reverse_accrual_period(period_id):
    authenticate([FINANCE_CONTROLLER])
    period = lookup.accrual_period(period_id)
    body = get_body()
    reversal_reason = req_string(body, "reversal_reason")

    plan = lookup.plan(period["plan_id"])

    if period["status"] != "POSTED":
        raise ApiError("ERR_ACCRUAL_ALREADY_POSTED",
                       "Reversal requires a period in POSTED")
    if plan["status"] == "SETTLED":
        raise ApiError("ERR_PLAN_ALREADY_SETTLED")
    this_start = db.as_date(period["period_start"])
    for other in _ordered_periods(plan["id"]):
        if other["id"] == period["id"]:
            continue
        if other["status"] == "POSTED" \
                and db.as_date(other["period_start"]) > this_start:
            raise ApiError("ERR_ACCRUAL_REVERSAL_OUT_OF_ORDER")

    period["reversal_reason"] = reversal_reason
    period["status"] = "REVERSED"
    db.touch(period)

    plan_before = db.snapshot(plan)
    rollup.refresh_accrual_ledger(plan)
    db.bump_if_changed(plan, plan_before)
    return object_response(accrual_out(period))


@bp.route("/accrual-periods/<period_id>", methods=["GET"])
def get_accrual_period(period_id):
    authenticate(READ_ROLES)
    return object_response(accrual_out(lookup.accrual_period(period_id)))


@bp.route("/accrual-periods", methods=["GET"])
def list_accrual_periods():
    authenticate(LIST_ROLES)
    plan_id = query_param("plan_id")
    status = query_param("status")

    records = list(db.accrual_periods.values())
    records.sort(key=lambda r: (r["period_start"], r["created_at"], r["_seq"]))
    if plan_id is not None:
        records = [r for r in records if r["plan_id"] == plan_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginated(records, accrual_out)
