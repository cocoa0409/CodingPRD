"""Spend and sales observations (PRD section 3.2)."""

from flask import Blueprint, request

import db as store
from db import base_row, db, touch
from errors import ApiError
from lookup import must, must_field
from middleware import DATA_ENGINEER, READ_ROLES, authenticate
from response import created, listing, ok
from services import ordering
from services.numeric import D, q0
from services.window import assert_period_aligned, refresh_window_counts
from validation import (field_date, field_decimal, field_int, get_body, query_bool)

bp = Blueprint("observations", __name__)

WRITABLE_WINDOW_STATES = ("OPEN", "REOPENED")


def _assert_window_writable(window):
    if window["status"] not in WRITABLE_WINDOW_STATES:
        raise ApiError("ERR_DATA_WINDOW_SEALED",
                       "The window is SEALED and accepts no further observations.")


# ------------------------------------------------------- spend observations

@bp.post("/mmm/spend-observations")
def create_spend_observation():
    authenticate((DATA_ENGINEER,))
    body = get_body()
    period_raw, period = field_date(body, "period_start_date")
    spend_cents = field_int(body, "spend_cents", minimum=0)
    impressions = field_int(body, "impressions", required=False, default=None, minimum=0)
    price_index = field_decimal(body, "price_index", required=False, default=None)
    distribution_index = field_decimal(body, "distribution_index", required=False, default=None)
    expected_version = field_int(body, "expected_data_window_version", minimum=0)

    window = must_field("data_windows", body, "data_window_id")
    channel = must_field("media_channels", body, "channel_id")

    if expected_version != window["version"]:
        raise ApiError("ERR_STALE_DATA_WINDOW_VERSION",
                       "expected_data_window_version %d does not match the window's version %d."
                       % (expected_version, window["version"]))

    _assert_window_writable(window)
    assert_period_aligned(window, period)

    incumbent = None
    for existing in store.spend_of_window(window["id"]):
        if existing["channel_id"] == channel["id"] and existing["_period_start_date"] == period:
            incumbent = existing
            break

    row = base_row("spend_observations")
    row.update({
        "data_window_id": window["id"],
        "channel_id": channel["id"],
        "period_start_date": period_raw,
        "spend_cents": spend_cents,
        "impressions": impressions,
        "price_index": price_index,
        "distribution_index": distribution_index,
        "superseded_by_id": None,
        "is_restatement": incumbent is not None,
        "data_window_version_after": None,
        "_period_start_date": period,
    })
    db.add("spend_observations", row)

    if incumbent is not None:
        incumbent["superseded_by_id"] = row["id"]
        touch(incumbent)

    refresh_window_counts(window)
    touch(window)
    row["data_window_version_after"] = window["version"]
    return created(row)


@bp.get("/mmm/spend-observations")
def list_spend_observations():
    authenticate(READ_ROLES)
    include_superseded = query_bool(request.args, "include_superseded", False)
    rows = db.all("spend_observations")
    if not include_superseded:
        rows = [r for r in rows if r["superseded_by_id"] is None]
    window_id = request.args.get("data_window_id")
    if window_id:
        rows = [r for r in rows if r["data_window_id"] == window_id]
    channel_id = request.args.get("channel_id")
    if channel_id:
        rows = [r for r in rows if r["channel_id"] == channel_id]
    superseded_by_id = request.args.get("superseded_by_id")
    if superseded_by_id:
        rows = [r for r in rows if r["superseded_by_id"] == superseded_by_id]
    return listing(ordering.sort_rows("spend_observations", rows), request.args)


@bp.get("/mmm/spend-observations/<observation_id>")
def get_spend_observation(observation_id):
    authenticate(READ_ROLES)
    return ok(must("spend_observations", observation_id))


# ------------------------------------------------------- sales observations

@bp.post("/mmm/sales-observations")
def create_sales_observation():
    authenticate((DATA_ENGINEER,))
    body = get_body()
    period_raw, period = field_date(body, "period_start_date")
    units_sold = field_int(body, "units_sold", minimum=1)
    revenue_cents = field_int(body, "revenue_cents", minimum=0)
    distribution_pct = field_decimal(body, "distribution_pct", required=False, default=None,
                                     minimum=0, maximum=100)
    macro_index = field_decimal(body, "macro_index", required=False, default=None)

    window = must_field("data_windows", body, "data_window_id")

    _assert_window_writable(window)

    for existing in store.sales_of_window(window["id"]):
        if existing["_period_start_date"] == period:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "A sales observation already exists for that period.")

    assert_period_aligned(window, period)

    row = base_row("sales_observations")
    row.update({
        "data_window_id": window["id"],
        "period_start_date": period_raw,
        "units_sold": units_sold,
        "revenue_cents": revenue_cents,
        "distribution_pct": distribution_pct,
        "macro_index": macro_index,
        "avg_price_cents": q0(D(revenue_cents) / D(units_sold)),
        "_period_start_date": period,
    })
    db.add("sales_observations", row)

    refresh_window_counts(window)
    touch(window)
    return created(row)


@bp.get("/mmm/sales-observations")
def list_sales_observations():
    authenticate(READ_ROLES)
    rows = db.all("sales_observations")
    window_id = request.args.get("data_window_id")
    if window_id:
        rows = [r for r in rows if r["data_window_id"] == window_id]
    return listing(ordering.sort_rows("sales_observations", rows), request.args)


@bp.get("/mmm/sales-observations/<observation_id>")
def get_sales_observation(observation_id):
    authenticate(READ_ROLES)
    return ok(must("sales_observations", observation_id))
