"""Service plans, collection zones, and holiday calendars (PRD §3.1)."""
from flask import Blueprint, request

import db
from errors import err
from response import ok, ok_list
from routes.helpers import gate
from services import validate as V
from services.common import new_record, new_holiday_record, touch, sort_by_created
from services.lookup import get_or_404
from services.serialize import plan_out, zone_out, holiday_out
from util import to_midnight, format_ts, format_date, parse_dt

bp = Blueprint("plans_zones", __name__)

PLAN_TIERS = {"BASIC", "STANDARD", "PREMIUM"}
CART_SIZES = {35, 65, 96}
PARITIES = {"EVEN", "ODD"}
SHIFTS = {"DELAY_ONE_DAY", "NONE"}


# --------------------------------------------------------------------------
# Service plans
# --------------------------------------------------------------------------
@bp.route("/service-plans", methods=["POST"])
def create_plan():
    gate({"Dispatcher"})
    body = V.get_body(request)
    tier = V.require_enum(body, "tier", PLAN_TIERS)
    trash = V.require_int(body, "trash_cart_size_gallons", allowed=CART_SIZES)
    recyc = V.require_int(body, "recycling_cart_size_gallons", allowed=CART_SIZES)
    monthly_base = V.require_int(body, "monthly_base_cents", minimum=0)
    extra_cart = V.require_int(body, "extra_cart_monthly_cents", minimum=0)
    extra_pickup = V.require_int(body, "extra_pickup_base_cents", minimum=0)
    bulk_item = V.require_int(body, "bulk_item_cents", minimum=0)

    rec = new_record({
        "tier": tier,
        "trash_cart_size_gallons": trash,
        "recycling_cart_size_gallons": recyc,
        "monthly_base_cents": monthly_base,
        "extra_cart_monthly_cents": extra_cart,
        "extra_pickup_base_cents": extra_pickup,
        "bulk_item_cents": bulk_item,
        "archived": False,
    })
    db.service_plans[rec["id"]] = rec
    return ok(plan_out(rec), 201)


@bp.route("/service-plans", methods=["GET"])
def list_plans():
    gate({"Dispatcher", "AccountHolder"})
    limit, offset = V.parse_pagination(request.args)
    include_archived = request.args.get("include_archived", "").lower() == "true"
    items = [p for p in db.service_plans.values() if include_archived or not p["archived"]]
    items = sort_by_created(items)
    total = len(items)
    page = V.paginate(items, limit, offset)
    return ok_list([plan_out(p) for p in page], limit, offset, total)


@bp.route("/service-plans/<pid>", methods=["GET"])
def get_plan(pid):
    gate({"Dispatcher", "AccountHolder"})
    p = get_or_404(db.service_plans, pid)
    return ok(plan_out(p))


@bp.route("/service-plans/<pid>/archive", methods=["POST"])
def archive_plan(pid):
    gate({"Dispatcher"})
    p = get_or_404(db.service_plans, pid)
    p["archived"] = True
    touch(p)
    return ok(plan_out(p))


# --------------------------------------------------------------------------
# Collection zones
# --------------------------------------------------------------------------
@bp.route("/collection-zones", methods=["POST"])
def create_zone():
    gate({"Dispatcher"})
    body = V.get_body(request)
    name = V.require_str(body, "name")
    weekday = V.require_int(body, "base_pickup_weekday", minimum=0, maximum=6)
    parity = V.require_enum(body, "recycling_week_parity", PARITIES)

    rec = new_record({
        "name": name,
        "base_pickup_weekday": weekday,
        "recycling_week_parity": parity,
    })
    db.collection_zones[rec["id"]] = rec
    return ok(zone_out(rec), 201)


@bp.route("/collection-zones/<zid>", methods=["GET"])
def get_zone(zid):
    gate({"Dispatcher", "AccountHolder"})
    z = get_or_404(db.collection_zones, zid)
    return ok(zone_out(z))


# --------------------------------------------------------------------------
# Holidays
# --------------------------------------------------------------------------
@bp.route("/collection-zones/<zid>/holidays", methods=["POST"])
def add_holiday(zid):
    gate({"Dispatcher"})
    z = get_or_404(db.collection_zones, zid)
    body = V.get_body(request)
    holiday_dt = V.require_dt(body, "holiday_date")
    shift = V.require_enum(body, "shift_direction", SHIFTS)

    hd = to_midnight(holiday_dt)
    hd_str = format_date(hd)
    # unique per (zone_id, holiday_date)
    for h in db.holidays.values():
        if h["zone_id"] == zid and to_midnight(parse_dt(h["holiday_date"])) == hd:
            raise err("ERR_INVALID_REQUEST", "A holiday already exists for this zone and date.")

    rec = new_holiday_record({
        "zone_id": zid,
        "holiday_date": hd_str,
        "shift_direction": shift,
    })
    db.holidays[rec["id"]] = rec
    return ok(holiday_out(rec), 201)


@bp.route("/collection-zones/<zid>/holidays", methods=["GET"])
def list_holidays(zid):
    gate({"Dispatcher", "AccountHolder"})
    get_or_404(db.collection_zones, zid)
    limit, offset = V.parse_pagination(request.args)
    items = [h for h in db.holidays.values() if h["zone_id"] == zid]
    items = sort_by_created(items)
    total = len(items)
    page = V.paginate(items, limit, offset)
    return ok_list([holiday_out(h) for h in page], limit, offset, total)
