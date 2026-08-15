"""Dividend event endpoints."""
from decimal import Decimal

from flask import Blueprint, request

from db import DB, clock_dt, new_id
from errors import ApiError
from middleware import ADMIN, ANY_ROLE, auth
from response import ok
from services import (
    DIVIDEND_STATUSES,
    execute_dividend,
    filter_enum,
    get_dividend,
    get_plan,
    list_response,
    ser_dividend,
    stamp,
    touch,
)
from util import as_iso_dt, as_pos_int, body, required, round_cents
from util import parse_dt

bp = Blueprint("dividends", __name__)


@bp.post("/plans/<plan_id>/dividend-events")
def declare_dividend(plan_id):
    auth(ADMIN)
    plan = get_plan(plan_id)
    data = body()
    amount = as_pos_int(
        required(data, "amount_per_share_cents"), "amount_per_share_cents"
    )
    record_date = as_iso_dt(required(data, "record_date"), "record_date")
    payable_date = as_iso_dt(required(data, "payable_date"), "payable_date")
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", 409, "Plan is not ACTIVE")
    rec = {
        "id": new_id(),
        "plan_id": plan_id,
        "amount_per_share_cents": amount,
        "record_date": record_date,
        "payable_date": payable_date,
        "status": "DECLARED",
        "closing_price_cents": None,
        "avg5_price_cents": None,
        "reinvestment_price_cents": None,
    }
    stamp(rec)
    DB["dividend_events"][rec["id"]] = rec
    return ok(ser_dividend(rec), status=201)


@bp.get("/plans/<plan_id>/dividend-events")
def list_dividends(plan_id):
    auth(ANY_ROLE)
    get_plan(plan_id)
    items = [
        ev for ev in DB["dividend_events"].values() if ev["plan_id"] == plan_id
    ]
    items = filter_enum(
        items, request.args.get("status"), "status", DIVIDEND_STATUSES, "status"
    )
    return list_response(items, ser_dividend)


@bp.post("/dividend-events/<did>/price")
def price_dividend(did):
    auth(ADMIN)
    ev = get_dividend(did)
    data = body()
    closing = as_pos_int(
        required(data, "closing_price_cents"), "closing_price_cents"
    )
    avg5 = as_pos_int(required(data, "avg5_price_cents"), "avg5_price_cents")
    if ev["status"] != "DECLARED":
        raise ApiError("ERR_INVALID_STATE", 409, "Dividend is not DECLARED")
    plan = get_plan(ev["plan_id"])
    # Pinned rounding order: the discounted price is rounded half-up to whole
    # cents before any share division takes place.
    reference = closing if plan["pricing_basis"] == "MARKET_CLOSE" else avg5
    reinvestment_price = round_cents(
        Decimal(reference) * (Decimal("1") - Decimal(str(plan["discount_pct"])))
    )
    ev["closing_price_cents"] = closing
    ev["avg5_price_cents"] = avg5
    ev["reinvestment_price_cents"] = reinvestment_price
    ev["status"] = "PRICED"
    touch(ev)
    return ok(ser_dividend(ev))


@bp.post("/dividend-events/<did>/execute")
def execute_dividend_route(did):
    auth(ADMIN)
    ev = get_dividend(did)
    if ev["status"] != "PRICED":
        raise ApiError("ERR_INVALID_STATE", 409, "Dividend is not PRICED")
    plan = get_plan(ev["plan_id"])
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", 409, "Plan is not ACTIVE")
    if clock_dt() < parse_dt(ev["payable_date"]):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Dividend payable_date has not been reached"
        )
    execute_dividend(ev)
    return ok(ser_dividend(ev))


@bp.post("/dividend-events/<did>/settle")
def settle_dividend(did):
    auth(ADMIN)
    ev = get_dividend(did)
    if ev["status"] != "REINVESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Dividend is not REINVESTED")
    ev["status"] = "SETTLED"
    touch(ev)
    return ok(ser_dividend(ev))
