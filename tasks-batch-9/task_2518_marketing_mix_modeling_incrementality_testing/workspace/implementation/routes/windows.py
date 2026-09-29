"""Data windows: creation, sealing and reopening (PRD sections 3.2, 3.3)."""

from decimal import Decimal

from flask import Blueprint, request

import db as store
from db import base_row, db, touch
from errors import ApiError
from lookup import must, must_field
from middleware import DATA_ENGINEER, READ_ROLES, authenticate
from response import created, listing, ok
from services import ordering
from services.market import sync_market
from services.model import cascade_window_reopened
from services.window import PERIOD_DAYS, windows_overlap
from validation import date_style, field_date, field_enum, field_string, get_body, invalid

bp = Blueprint("windows", __name__)

GRANULARITIES = ("WEEKLY", "DAILY")
MIN_SEALED_SALES_PERIODS = 4
FULL_COVERAGE = Decimal("100.00")


@bp.post("/mmm/data-windows")
def create_window():
    authenticate((DATA_ENGINEER,))
    body = get_body()
    start_raw, start = field_date(body, "window_start_date")
    end_raw, end = field_date(body, "window_end_date")
    granularity = field_enum(body, "granularity", GRANULARITIES)
    if end <= start:
        raise invalid("window_end_date must be strictly after window_start_date.")
    span_days = (end - start).days
    period_days = PERIOD_DAYS[granularity]
    if span_days % period_days != 0:
        raise invalid("The window span must divide evenly into whole %s periods." % granularity)
    expected_period_count = span_days // period_days

    market = must_field("markets", body, "market_id")

    for existing in store.windows_of_market(market["id"]):
        if existing["granularity"] != granularity:
            continue
        if windows_overlap(start, end, existing["_window_start_date"],
                           existing["_window_end_date"]):
            raise ApiError("ERR_DATA_WINDOW_OVERLAP",
                           "The window overlaps an existing %s window of this market."
                           % granularity)

    row = base_row("data_windows")
    row.update({
        "market_id": market["id"],
        "window_start_date": start_raw,
        "window_end_date": end_raw,
        "granularity": granularity,
        "expected_period_count": expected_period_count,
        "sales_period_count": 0,
        "spend_observation_count": 0,
        "lag_completeness_pct": Decimal("0.00"),
        "status": "OPEN",
        "reopen_reason": None,
        "reopen_count": 0,
        "_window_start_date": start,
        "_window_end_date": end,
        "_date_style": date_style(start_raw),
    })
    db.add("data_windows", row)
    return created(row)


@bp.get("/mmm/data-windows")
def list_windows():
    authenticate(READ_ROLES)
    rows = db.all("data_windows")
    market_id = request.args.get("market_id")
    if market_id:
        rows = [r for r in rows if r["market_id"] == market_id]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    granularity = request.args.get("granularity")
    if granularity:
        rows = [r for r in rows if r["granularity"] == granularity]
    return listing(ordering.sort_rows("data_windows", rows), request.args)


@bp.get("/mmm/data-windows/<window_id>")
def get_window(window_id):
    authenticate(READ_ROLES)
    return ok(must("data_windows", window_id))


@bp.post("/mmm/data-windows/<window_id>/seal")
def seal_window(window_id):
    authenticate((DATA_ENGINEER,))
    window = must("data_windows", window_id)
    if window["status"] not in ("OPEN", "REOPENED"):
        raise ApiError("ERR_DATA_WINDOW_INVALID_STATE",
                       "A window in %s cannot be sealed." % window["status"])
    if db.clock.date() < window["_window_end_date"]:
        raise ApiError("ERR_DATA_WINDOW_NOT_ELAPSED",
                       "The logical clock has not reached window_end_date.")
    if window["sales_period_count"] < MIN_SEALED_SALES_PERIODS:
        raise ApiError("ERR_DATA_WINDOW_INCOMPLETE",
                       "A window needs at least %d sales periods to be sealed."
                       % MIN_SEALED_SALES_PERIODS)
    if window["lag_completeness_pct"] != FULL_COVERAGE:
        raise ApiError("ERR_DATA_WINDOW_INCOMPLETE",
                       "Sales coverage must be exactly 100.00 percent to seal the window.")
    window["status"] = "SEALED"
    touch(window)
    sync_market(db.markets[window["market_id"]])
    return ok(window)


@bp.post("/mmm/data-windows/<window_id>/reopen")
def reopen_window(window_id):
    authenticate((DATA_ENGINEER,))
    window = must("data_windows", window_id)
    body = get_body()
    reason = field_string(body, "reason")
    if window["status"] != "SEALED":
        raise ApiError("ERR_DATA_WINDOW_INVALID_STATE",
                       "Only a SEALED window can be reopened.")
    window["status"] = "REOPENED"
    window["reopen_reason"] = reason
    window["reopen_count"] = window["reopen_count"] + 1
    touch(window)
    cascade_window_reopened(window)
    return ok(window)
