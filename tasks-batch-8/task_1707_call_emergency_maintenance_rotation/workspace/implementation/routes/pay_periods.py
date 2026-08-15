"""PayPeriod and PayStatement endpoints."""

from flask import Blueprint, request

from db import store, clock
from errors import (
    ApiError,
    ERR_PAY_PERIOD_NOT_FOUND,
    ERR_PAY_PERIOD_INVALID_STATE,
    ERR_PAY_STATEMENT_NOT_FOUND,
    ERR_PERIOD_NOT_ENDED,
    ERR_OPEN_SHIFTS_IN_PERIOD,
    ERR_INVALID_REQUEST,
)
from helpers import (
    body,
    req_dt,
    new_id,
    serialize_pay_period,
    serialize_pay_statement,
    touch,
    pagination_params,
)
from middleware import get_actor, require_role
from response import success_object, success_list
from services.calculations import compute_standby_final

bp = Blueprint("pay_periods", __name__)

READ_ROLES = {"PropertyAdmin", "MaintenanceSupervisor"}


@bp.route("/v1/pay-periods", methods=["POST"])
def create_pay_period():
    actor = get_actor()
    require_role(actor, {"PropertyAdmin"})
    data = body()
    period_start = req_dt(data, "period_start")
    period_end = req_dt(data, "period_end")
    if period_end <= period_start:
        raise ApiError(ERR_INVALID_REQUEST, "period_end must be strictly after period_start", 400)
    now = clock.now()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 0,
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "_seq": store.next_seq(),
    }
    store.pay_periods[rec["id"]] = rec
    return success_object(serialize_pay_period(rec), 201)


def _get_period_or_404(period_id):
    rec = store.pay_periods.get(period_id)
    if rec is None:
        raise ApiError(ERR_PAY_PERIOD_NOT_FOUND, "Pay period not found", 404)
    return rec


@bp.route("/v1/pay-periods/<payPeriodId>", methods=["GET"])
def get_pay_period(payPeriodId):
    actor = get_actor()
    require_role(actor, READ_ROLES)
    rec = _get_period_or_404(payPeriodId)
    return success_object(serialize_pay_period(rec))


@bp.route("/v1/pay-periods/<payPeriodId>/close", methods=["POST"])
def close_pay_period(payPeriodId):
    actor = get_actor()
    require_role(actor, {"PropertyAdmin"})
    rec = _get_period_or_404(payPeriodId)
    if rec["status"] != "OPEN":
        raise ApiError(ERR_PAY_PERIOD_INVALID_STATE, "Pay period is not OPEN", 409)
    now = clock.now()
    if rec["period_end"] > now:
        raise ApiError(ERR_PERIOD_NOT_ENDED, "Pay period has not ended", 409)
    for s in store.rotation_shifts.values():
        if (
            rec["period_start"] <= s["start_at"] < rec["period_end"]
            and s["status"] in ("PUBLISHED", "ACTIVE")
        ):
            raise ApiError(
                ERR_OPEN_SHIFTS_IN_PERIOD,
                "Shifts in the period remain PUBLISHED or ACTIVE",
                409,
            )
    rec["status"] = "CLOSED"
    touch(rec)
    # Group COMPLETED shifts starting in the period by technician
    shifts_by_tech = {}
    for s in store.rotation_shifts.values():
        if (
            s["status"] == "COMPLETED"
            and rec["period_start"] <= s["start_at"] < rec["period_end"]
        ):
            shifts_by_tech.setdefault(s["technician_id"], []).append(s)
    for technician_id, shifts in shifts_by_tech.items():
        tech = store.technicians.get(technician_id)
        standby_total, standby_final = compute_standby_final(shifts, tech)
        callback_minutes_total = 0
        callback_pay_final = 0
        for t in store.call_tickets.values():
            if (
                t["assigned_technician_id"] == technician_id
                and t["status"] == "CLOSED"
                and t["closed_at"] is not None
                and rec["period_start"] <= t["closed_at"] < rec["period_end"]
            ):
                callback_minutes_total += t["callback_minutes"] or 0
                callback_pay_final += t["callback_pay_cents"] or 0
        stmt = {
            "id": new_id(),
            "created_at": now,
            "pay_period_id": rec["id"],
            "technician_id": technician_id,
            "standby_minutes_total": standby_total,
            "standby_pay_final_cents": standby_final,
            "callback_minutes_total": callback_minutes_total,
            "callback_pay_final_cents": callback_pay_final,
            "total_pay_cents": standby_final + callback_pay_final,
            "_seq": store.next_seq(),
        }
        store.pay_statements[stmt["id"]] = stmt
    return success_object(serialize_pay_period(rec))


@bp.route("/v1/pay-statements", methods=["GET"])
def list_pay_statements():
    actor = get_actor()
    require_role(actor, READ_ROLES)
    limit, offset = pagination_params()
    items = list(store.pay_statements.values())
    for key in ("pay_period_id", "technician_id"):
        v = request.args.get(key)
        if v is not None:
            items = [s for s in items if s[key] == v]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_pay_statement(s) for s in page], limit, offset, total)


@bp.route("/v1/pay-statements/<payStatementId>", methods=["GET"])
def get_pay_statement(payStatementId):
    actor = get_actor()
    require_role(actor, READ_ROLES)
    rec = store.pay_statements.get(payStatementId)
    if rec is None:
        raise ApiError(ERR_PAY_STATEMENT_NOT_FOUND, "Pay statement not found", 404)
    return success_object(serialize_pay_statement(rec))
