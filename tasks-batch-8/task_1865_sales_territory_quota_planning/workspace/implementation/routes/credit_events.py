"""CreditEvent endpoints."""
from datetime import date

from flask import Blueprint, request

from db import store, logical_today
from errors import ApiError
from middleware import get_user_context, require_role
from response import success_object, success_list
from util import (get_body, reject_unknown_fields, require_fields, req_int,
                  parse_date, find_or_404, paginate, stamp_new, touch)
from services import calc

bp = Blueprint("credit_events", __name__)

ADMIN = ("SalesOpsAdmin",)
ALL = ("SalesOpsAdmin", "SalesOpsAnalyst", "RevOpsManager", "SalesRep")


@bp.route("/sales-planning/credit-events", methods=["POST"])
def create_credit_event():
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    body = get_body()
    reject_unknown_fields(body, {"plan_year_id", "account_id", "amount_cents", "booking_date"})
    require_fields(body, ["plan_year_id", "account_id", "amount_cents", "booking_date"])
    plan = find_or_404(store.plan_years, body["plan_year_id"], "plan year")
    account = find_or_404(store.accounts, body["account_id"], "account")
    amount = req_int(body, "amount_cents")
    booking = parse_date(body["booking_date"], "booking_date")

    today = logical_today()
    if booking > today:
        raise ApiError("ERR_INVALID_REQUEST",
                       "booking_date lies in the future", 400)

    # Tier 4: plan gate
    if plan["status"] not in ("COMMUNICATED", "LOCKED"):
        raise ApiError("ERR_PLAN_NOT_COMMUNICATED",
                       "Credit events require plan status COMMUNICATED or LOCKED", 409)

    # Tier 5: cross-plan
    if account["plan_year_id"] != plan["id"]:
        raise ApiError("ERR_CROSS_PLAN_REFERENCE",
                       "account_id belongs to a different plan year", 409)

    # Tier 6: within plan year
    p_start = date.fromisoformat(plan["start_date"])
    p_end = date.fromisoformat(plan["end_date"])
    if not (p_start <= booking <= p_end):
        raise ApiError("ERR_DATE_OUT_OF_PLAN_YEAR",
                       "booking_date falls outside the plan year", 422)

    # Tier 7: resolvable + staffed
    if account["assigned_territory_id"] is None:
        raise ApiError("ERR_ACCOUNT_UNASSIGNED",
                       "Account has no assigned territory", 409)
    territory = find_or_404(store.territories, account["assigned_territory_id"], "territory")
    credited = calc.credited_reps_for(territory["id"], booking.isoformat())
    if not credited:
        raise ApiError("ERR_TERRITORY_UNCOVERED",
                       "No ACTIVE rep assignment covers the credit split", 409)

    # Tier 8: amount positive
    if amount <= 0:
        raise ApiError("ERR_AMOUNT_NOT_POSITIVE", "amount_cents must be > 0", 422)

    shares = calc.split_amount(amount, len(credited))
    created = []
    for asg, amt in zip(credited, shares):
        ev = stamp_new({
            "plan_year_id": plan["id"],
            "account_id": account["id"],
            "rep_id": asg["rep_id"],
            "event_type": "BOOKING",
            "amount_cents": amt,
            "booking_date": booking.isoformat(),
            "source_change_request_id": None,
            "parent_credit_event_id": None,
            "status": "POSTED",
        })
        store.credit_events[ev["id"]] = ev
        created.append(ev)

    # attainment rollup for each credited rep
    for rep_id in {e["rep_id"] for e in created}:
        calc.recompute_attainment_rollup(rep_id, plan["id"])

    return success_list_raw([calc.ser_credit_event(e) for e in created])


def success_list_raw(items):
    """201 creation returning an array: envelope with response_type array, no pagination fields."""
    from response import _request_id
    from db import request_timestamp
    from flask import jsonify
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": request_timestamp(),
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 201


@bp.route("/sales-planning/credit-events", methods=["GET"])
def list_credit_events():
    ctx = get_user_context()
    require_role(ctx, ALL)
    items = list(store.credit_events.values())
    if (v := request.args.get("plan_year_id")) is not None:
        items = [e for e in items if e["plan_year_id"] == v]
    if (v := request.args.get("account_id")) is not None:
        items = [e for e in items if e["account_id"] == v]
    if (v := request.args.get("rep_id")) is not None:
        items = [e for e in items if e["rep_id"] == v]
    if (v := request.args.get("source_change_request_id")) is not None:
        items = [e for e in items if e["source_change_request_id"] == v]
    if (v := request.args.get("parent_credit_event_id")) is not None:
        items = [e for e in items if e["parent_credit_event_id"] == v]
    if (v := request.args.get("event_type")) is not None:
        items = [e for e in items if e["event_type"] == v]
    if (v := request.args.get("status")) is not None:
        items = [e for e in items if e["status"] == v]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    page, limit, offset, total = paginate(items, request.args)
    return success_list([calc.ser_credit_event(e) for e in page], limit, offset, total)


@bp.route("/sales-planning/credit-events/<eid>", methods=["GET"])
def get_credit_event(eid):
    ctx = get_user_context()
    require_role(ctx, ALL)
    e = find_or_404(store.credit_events, eid, "credit event")
    return success_object(calc.ser_credit_event(e))


@bp.route("/sales-planning/credit-events/<eid>/reverse", methods=["POST"])
def reverse_credit_event(eid):
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    e = find_or_404(store.credit_events, eid, "credit event")
    get_body()
    plan = find_or_404(store.plan_years, e["plan_year_id"], "plan year")
    if plan["status"] not in ("COMMUNICATED", "LOCKED"):
        raise ApiError("ERR_PLAN_NOT_COMMUNICATED",
                       "Credit event reversal requires plan status COMMUNICATED or LOCKED", 409)
    if e["status"] != "POSTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot reverse credit event in status {e['status']}", 409)
    e["status"] = "REVERSED"
    touch(e)
    calc.recompute_attainment_rollup(e["rep_id"], plan["id"])
    return success_object(calc.ser_credit_event(e))
