"""Rental unit + reservation endpoints."""
import math
from datetime import timedelta

from flask import Blueprint, request

import store
from errors import err
import core as c

bp = Blueprint("rentals", __name__)


# ----------------------------- Rental units --------------------------------
@bp.post("/coop/rental-units")
def create_unit():
    ctx = c.authenticate()
    c.authorize(ctx, {"CoopAdmin"})
    body = c.get_body()
    product_id = c.require_str(body, "product_id")
    asset_tag = c.require_str(body, "asset_tag")
    product = c.lookup("products", product_id)
    if not product["is_rentable"]:
        raise err("ERR_VALIDATION", "product is not rentable")
    for u in store.rental_units.values():
        if u["asset_tag"] == asset_tag:
            raise err("ERR_VALIDATION", "asset_tag already exists")
    unit = {
        "product_id": product_id,
        "asset_tag": asset_tag,
        "status": "AVAILABLE",
        "condition": "GOOD",
    }
    store.stamp_new(unit)
    store.rental_units[unit["id"]] = unit
    return c.ok(c.ser_rental_unit(unit), 201)


@bp.get("/coop/rental-units")
def list_units():
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    items = list(store.rental_units.values())
    if product_id is not None:
        items = [u for u in items if u["product_id"] == product_id]
    if status is not None:
        items = [u for u in items if u["status"] == status]
    return c.paginate_and_serialize(items, c.ser_rental_unit)


@bp.get("/coop/rental-units/<uid>")
def get_unit(uid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    u = c.lookup("rental_units", uid)
    return c.ok(c.ser_rental_unit(u))


@bp.post("/coop/rental-units/<uid>/service")
def service_unit(uid):
    ctx = c.authenticate()
    c.authorize(ctx, {"StoreStaff", "CoopAdmin"})
    body = c.get_body()
    action = c.require_enum(body, "action", {"RETIRE", "RESTORE"})
    u = c.lookup("rental_units", uid)
    if action == "RETIRE":
        if u["status"] != "AVAILABLE":
            raise err("ERR_INVALID_STATE", "unit must be AVAILABLE to retire")
        u["status"] = "OUT_OF_SERVICE"
    else:  # RESTORE
        if u["status"] != "OUT_OF_SERVICE":
            raise err("ERR_INVALID_STATE", "unit must be OUT_OF_SERVICE to restore")
        u["status"] = "AVAILABLE"
        u["condition"] = "GOOD"
    store.touch(u)
    return c.ok(c.ser_rental_unit(u))


# ----------------------------- Reservations --------------------------------
def _rental_days(start, end):
    secs = (end - start).total_seconds()
    return max(1, math.ceil(secs / 86400.0))


def _compute_fee(product, member, rental_days, start):
    raw = product["base_daily_rate_cents"] * rental_days
    is_peak = c.PEAK_START <= start < c.PEAK_END
    peak_adjusted = c.round_half_up(c.Decimal(raw) * c.PEAK_MULTIPLIER) if is_peak else raw
    tier_disc = c.TIER_RENTAL_DISCOUNT[member["membership_tier"]]
    discounted = c.round_half_up(c.Decimal(peak_adjusted) * (c.Decimal(1) - tier_disc))
    return min(discounted, product["replacement_value_cents"])


def _window_conflict(unit_id, new_start, new_end, exclude_id=None):
    buf = timedelta(days=c.TURNAROUND_BUFFER_DAYS)
    for r in store.reservations.values():
        if r["rental_unit_id"] != unit_id:
            continue
        if exclude_id and r["id"] == exclude_id:
            continue
        if r["status"] not in ("RESERVED", "PICKED_UP"):
            continue
        ex_start = store._parse_instant(r["start_date"])
        ex_end = store._parse_instant(r["end_date"])
        if new_start < ex_end + buf and ex_start < new_end + buf:
            return True
    return False


@bp.post("/coop/reservations")
def create_reservation():
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff"})
    body = c.get_body()
    member_id = c.require_str(body, "member_id")
    rental_unit_id = c.require_str(body, "rental_unit_id")
    start_raw = c.require_str(body, "start_date")
    end_raw = c.require_str(body, "end_date")
    c.require_owner_member(ctx, member_id)
    member = c.lookup("members", member_id)
    unit = c.lookup("rental_units", rental_unit_id)
    # state / cross-entity state
    if member["membership_status"] != "ACTIVE":
        raise err("ERR_MEMBERSHIP_NOT_ACTIVE", "member is not ACTIVE")
    if unit["status"] == "OUT_OF_SERVICE":
        raise err("ERR_RENTAL_UNIT_UNAVAILABLE", "rental unit is out of service")
    start = store._parse_instant(start_raw)
    end = store._parse_instant(end_raw)
    if not (end > start):
        raise err("ERR_INVALID_INTERVAL", "end_date must be after start_date")
    if _window_conflict(rental_unit_id, start, end):
        raise err("ERR_RENTAL_WINDOW_CONFLICT", "reservation window conflicts with an active reservation")
    product = store.products[unit["product_id"]]
    rental_days = _rental_days(start, end)
    fee = _compute_fee(product, member, rental_days, start)
    res = {
        "member_id": member_id,
        "rental_unit_id": rental_unit_id,
        "product_id": unit["product_id"],
        "start_date": start_raw,
        "end_date": end_raw,
        "rental_days": rental_days,
        "status": "RESERVED",
        "rental_fee_cents": fee,
    }
    store.stamp_new(res)
    store.reservations[res["id"]] = res
    return c.ok(c.ser_reservation(res), 201)


@bp.get("/coop/reservations")
def list_reservations():
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    items = list(store.reservations.values())
    if ctx.role == "Member":
        items = [r for r in items if r["member_id"] == ctx.user_id]
    for key in ("member_id", "rental_unit_id", "product_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r[key] == val]
    return c.paginate_and_serialize(items, c.ser_reservation)


@bp.get("/coop/reservations/<rid>")
def get_reservation(rid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    r = c.lookup("reservations", rid)
    c.require_owner_member(ctx, r["member_id"])
    return c.ok(c.ser_reservation(r))


@bp.post("/coop/reservations/<rid>/pickup")
def pickup(rid):
    ctx = c.authenticate()
    c.authorize(ctx, {"StoreStaff"})
    r = c.lookup("reservations", rid)
    if r["status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "reservation is not RESERVED")
    unit = store.rental_units[r["rental_unit_id"]]
    if unit["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "rental unit is not AVAILABLE")
    r["status"] = "PICKED_UP"
    store.touch(r)
    unit["status"] = "RENTED_OUT"
    store.touch(unit)
    return c.ok(c.ser_reservation(r))


@bp.post("/coop/reservations/<rid>/return")
def return_unit(rid):
    ctx = c.authenticate()
    c.authorize(ctx, {"StoreStaff"})
    body = c.get_body()
    condition = c.require_enum(body, "condition", {"GOOD", "DAMAGED"})
    r = c.lookup("reservations", rid)
    if r["status"] != "PICKED_UP":
        raise err("ERR_INVALID_STATE", "reservation is not PICKED_UP")
    unit = store.rental_units[r["rental_unit_id"]]
    if condition == "GOOD":
        r["status"] = "CLOSED"
        store.touch(r)
        unit["status"] = "AVAILABLE"
        store.touch(unit)
    else:  # DAMAGED cascade
        r["status"] = "DAMAGE_ASSESSED"
        store.touch(r)
        unit["status"] = "OUT_OF_SERVICE"
        unit["condition"] = "DAMAGED"
        store.touch(unit)
        repair = {
            "member_id": None,
            "product_id": None,
            "rental_unit_id": unit["id"],
            "purchase_date": None,
            "repair_stage": "RECEIVED",
            "billing_stage": "UNBILLED",
            "warranty_status": "UNDETERMINED",
            "labor_cents": 0,
            "parts_cents": 0,
            "billed_cents": None,
        }
        store.stamp_new(repair)
        store.repair_orders[repair["id"]] = repair
    return c.ok(c.ser_reservation(r))


@bp.post("/coop/reservations/<rid>/cancel")
def cancel_reservation(rid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff"})
    r = c.lookup("reservations", rid)
    c.require_owner_member(ctx, r["member_id"])
    if r["status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "reservation is not RESERVED")
    r["status"] = "CANCELLED"
    store.touch(r)
    return c.ok(c.ser_reservation(r))
