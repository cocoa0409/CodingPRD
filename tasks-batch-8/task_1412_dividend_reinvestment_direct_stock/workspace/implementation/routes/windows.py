"""Purchase window endpoints."""
from datetime import datetime, time, timedelta, timezone

from flask import Blueprint, request

from db import DB, clock_dt, new_id
from errors import ApiError
from middleware import ADMIN, ANY_ROLE, auth
from response import ok
from services import (
    WINDOW_STATUSES,
    filter_enum,
    get_plan,
    get_window,
    list_response,
    ser_window,
    settle_window,
    stamp,
    touch,
)
from util import as_iso_dt, as_pos_int, body, parse_dt, required

bp = Blueprint("windows", __name__)


def _blackout_intersects(plan_id, opens, closes):
    """Blackout: CLOSED interval [record_date - 2 days 00:00:00Z,
    payable_date 23:59:59Z] of any non-SETTLED dividend. Touching either
    boundary counts as intersection."""
    for ev in DB["dividend_events"].values():
        if ev["plan_id"] != plan_id or ev["status"] == "SETTLED":
            continue
        bstart = datetime.combine(
            parse_dt(ev["record_date"]).date() - timedelta(days=2),
            time(0, 0, 0),
            tzinfo=timezone.utc,
        )
        bend = datetime.combine(
            parse_dt(ev["payable_date"]).date(),
            time(23, 59, 59, 999999),
            tzinfo=timezone.utc,
        )
        if opens <= bend and closes >= bstart:
            return True
    return False


def _overlap_intersects(plan_id, opens, closes):
    """Half-open [opens_at, closes_at) vs any existing non-SETTLED window of
    the same plan; back-to-back adjacency is allowed."""
    for w in DB["purchase_windows"].values():
        if w["plan_id"] != plan_id or w["status"] == "SETTLED":
            continue
        wo = parse_dt(w["opens_at"])
        wc = parse_dt(w["closes_at"])
        if opens < wc and closes > wo:
            return True
    return False


@bp.post("/plans/<plan_id>/purchase-windows")
def create_window(plan_id):
    auth(ADMIN)
    plan = get_plan(plan_id)
    data = body()
    opens_at = as_iso_dt(required(data, "opens_at"), "opens_at")
    closes_at = as_iso_dt(required(data, "closes_at"), "closes_at")
    price_cents = as_pos_int(required(data, "price_cents"), "price_cents")
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", 409, "Plan is not ACTIVE")
    opens = parse_dt(opens_at)
    closes = parse_dt(closes_at)
    # Schedule sanity: opens_at < closes_at and opens_at not in the past.
    if not (opens < closes) or opens < clock_dt():
        raise ApiError(
            "ERR_WINDOW_SCHEDULE_INVALID",
            422,
            "opens_at must be before closes_at and not in the past",
        )
    if _blackout_intersects(plan_id, opens, closes):
        raise ApiError(
            "ERR_WINDOW_DIVIDEND_BLACKOUT",
            422,
            "Window intersects a dividend blackout interval",
        )
    if _overlap_intersects(plan_id, opens, closes):
        raise ApiError(
            "ERR_WINDOW_OVERLAP",
            422,
            "Window overlaps an existing non-SETTLED window of this plan",
        )
    rec = {
        "id": new_id(),
        "plan_id": plan_id,
        "opens_at": opens_at,
        "closes_at": closes_at,
        "price_cents": price_cents,
        "status": "SCHEDULED",
        "submitted_total_cents": 0,
    }
    stamp(rec)
    DB["purchase_windows"][rec["id"]] = rec
    return ok(ser_window(rec), status=201)


@bp.get("/plans/<plan_id>/purchase-windows")
def list_windows(plan_id):
    auth(ANY_ROLE)
    get_plan(plan_id)
    items = [
        w for w in DB["purchase_windows"].values() if w["plan_id"] == plan_id
    ]
    items = filter_enum(
        items, request.args.get("status"), "status", WINDOW_STATUSES, "status"
    )
    return list_response(items, ser_window)


@bp.get("/purchase-windows/<wid>")
def get_one_window(wid):
    auth(ANY_ROLE)
    return ok(ser_window(get_window(wid)))


@bp.post("/purchase-windows/<wid>/open")
def open_window(wid):
    auth(ADMIN)
    w = get_window(wid)
    if w["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Window is not SCHEDULED")
    plan = get_plan(w["plan_id"])
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", 409, "Plan is not ACTIVE")
    now = clock_dt()
    # Half-open interval: opens_at <= clock < closes_at.
    if not (parse_dt(w["opens_at"]) <= now < parse_dt(w["closes_at"])):
        raise ApiError(
            "ERR_WINDOW_OPEN_TOO_EARLY",
            422,
            "Logical clock is outside [opens_at, closes_at)",
        )
    w["status"] = "OPEN"
    touch(w)
    return ok(ser_window(w))


@bp.post("/purchase-windows/<wid>/close")
def close_window(wid):
    auth(ADMIN)
    w = get_window(wid)
    if w["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Window is not OPEN")
    if clock_dt() < parse_dt(w["closes_at"]):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Window closes_at has not been reached"
        )
    w["status"] = "CLOSED"
    touch(w)
    return ok(ser_window(w))


@bp.post("/purchase-windows/<wid>/settle")
def settle_window_route(wid):
    auth(ADMIN)
    w = get_window(wid)
    if w["status"] != "CLOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Window is not CLOSED")
    settle_window(w)
    return ok(ser_window(w))
