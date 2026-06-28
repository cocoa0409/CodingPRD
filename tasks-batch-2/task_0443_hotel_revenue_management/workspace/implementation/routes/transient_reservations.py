"""TransientReservation endpoints (PRD §3.9)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, new_id
from middleware import authenticate, require_role
from response import success, list_success
from errors import (
    err, ERR_INVALID_REQUEST, ERR_FK_NOT_FOUND, ERR_LOS_VIOLATION,
    ERR_INVALID_STATE, ERR_RATE_NOT_PUBLISHED, ERR_MISSING_INVENTORY_DAY,
    ERR_OVERSELL_LIMIT_EXCEEDED, ERR_PLAN_CLOSED,
)
from services.common import (
    get_body, require_str, require_int, require_datetime,
    stay_date_midnight, iso_out, stamp_new, bump,
    parse_pagination, sort_by_created, get_or_404,
)
from services.serialize import ser_transient_reservation
from services.calc import recompute_availability, recompute_property_kpi

bp = Blueprint("transient_reservations", __name__)

READ_ROLES = {"RevenueManager", "Analyst"}


@bp.route("/transient-reservations", methods=["POST"])
def create_reservation():
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    body = get_body()
    room_type_id = require_str(body, "room_type_id")
    rate_plan_id = require_str(body, "rate_plan_id")
    arrival_dt = require_datetime(body, "arrival_date")
    nights = require_int(body, "nights")
    if nights < 1:
        raise err(ERR_INVALID_REQUEST, "nights must be >= 1")
    rooms = require_int(body, "rooms")
    if rooms < 1:
        raise err(ERR_INVALID_REQUEST, "rooms must be >= 1")

    # FK resolution.
    rt = db.room_types.get(room_type_id)
    if rt is None:
        raise err(ERR_FK_NOT_FOUND, "room_type_id does not reference an existing room type")
    plan = db.rate_plans.get(rate_plan_id)
    if plan is None:
        raise err(ERR_FK_NOT_FOUND, "rate_plan_id does not reference an existing rate plan")

    # LOS check at create against this plan's band.
    _check_los(plan, nights)

    arrival_mid = stay_date_midnight(arrival_dt)
    rec = {
        "id": new_id(),
        "room_type_id": room_type_id,
        "rate_plan_id": rate_plan_id,
        "arrival_date": arrival_mid.strftime("%Y-%m-%d"),
        "arrival_date_iso": iso_out(arrival_mid),
        "nights": nights,
        "rooms": rooms,
        "status": "HELD",
        "booked_rate": None,
        "_seq": db.next_seq(),
    }
    stamp_new(rec)
    db.transient_reservations[rec["id"]] = rec
    return success(ser_transient_reservation(rec), status=201)


@bp.route("/transient-reservations/<tid>", methods=["GET"])
def get_reservation(tid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    rec = get_or_404(db.transient_reservations, tid)
    return success(ser_transient_reservation(rec), status=200)


@bp.route("/transient-reservations", methods=["GET"])
def list_reservations():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    room_type_id = request.args.get("room_type_id")
    rate_plan_id = request.args.get("rate_plan_id")
    status = request.args.get("status")
    items = []
    for t in db.transient_reservations.values():
        if room_type_id is not None and t["room_type_id"] != room_type_id:
            continue
        if rate_plan_id is not None and t["rate_plan_id"] != rate_plan_id:
            continue
        if status is not None and t["status"] != status:
            continue
        items.append(t)
    items = sort_by_created(items)
    total = len(items)
    page = [ser_transient_reservation(t) for t in items[offset:offset + limit]]
    return list_success(page, limit, offset, total)


@bp.route("/transient-reservations/<tid>/confirm", methods=["POST"])
def confirm_reservation(tid):
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    rec = get_or_404(db.transient_reservations, tid)
    plan = db.rate_plans.get(rec["rate_plan_id"])

    # Gating order (PRD §3.9): state -> plan ACTIVE & published -> LOS ->
    # inventory days exist -> per-night availability.
    if rec["status"] != "HELD":
        raise err(ERR_INVALID_STATE, "Reservation is not in HELD state")
    if plan is None or plan["status"] != "ACTIVE":
        raise err(ERR_PLAN_CLOSED, "Rate plan is CLOSED")
    if plan["published_rate"] is None:
        raise err(ERR_RATE_NOT_PUBLISHED, "Rate plan has no published_rate yet")

    _check_los(plan, rec["nights"])

    invs = _require_inventory_days(rec)

    rooms = rec["rooms"]
    for inv in invs:
        recompute_availability(inv)
        if inv["rooms_available"] < rooms:
            raise err(ERR_OVERSELL_LIMIT_EXCEEDED, "A night cannot accommodate the reservation rooms")

    # Capture booked_rate from the plan's current published_rate.
    booked_rate = plan["published_rate"]
    rec["booked_rate"] = booked_rate
    rec["status"] = "CONFIRMED"
    bump(rec)

    # Each overlapping InventoryDay: transient_sold_rooms += rooms;
    # transient_revenue += rooms*booked_rate; recompute + bump.
    from decimal import Decimal, ROUND_HALF_UP
    for inv in invs:
        inv["transient_sold_rooms"] += rooms
        added = Decimal(str(rooms)) * Decimal(str(booked_rate))
        new_rev = Decimal(str(inv["transient_revenue"])) + added
        inv["transient_revenue"] = float(new_rev.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        recompute_availability(inv)
        bump(inv)

    _recompute_kpi_for_room_type(rec["room_type_id"])
    return success(ser_transient_reservation(rec), status=200)


@bp.route("/transient-reservations/<tid>/check-out", methods=["POST"])
def checkout_reservation(tid):
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    rec = get_or_404(db.transient_reservations, tid)
    if rec["status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Reservation is not in CONFIRMED state")
    rec["status"] = "CHECKED_OUT"
    # Transient counts retained; no inventory release.
    bump(rec)
    return success(ser_transient_reservation(rec), status=200)


@bp.route("/transient-reservations/<tid>/cancel", methods=["POST"])
def cancel_reservation(tid):
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    rec = get_or_404(db.transient_reservations, tid)
    status = rec["status"]
    if status not in ("HELD", "CONFIRMED"):
        raise err(ERR_INVALID_STATE, "Reservation cannot be cancelled from its current state")

    was_confirmed = status == "CONFIRMED"
    rec["status"] = "CANCELLED"
    bump(rec)

    if was_confirmed:
        rooms = rec["rooms"]
        booked_rate = rec["booked_rate"]
        from decimal import Decimal, ROUND_HALF_UP
        invs = _inventory_days_for(rec)
        for inv in invs:
            inv["transient_sold_rooms"] -= rooms
            removed = Decimal(str(rooms)) * Decimal(str(booked_rate))
            new_rev = Decimal(str(inv["transient_revenue"])) - removed
            inv["transient_revenue"] = float(new_rev.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            recompute_availability(inv)
            bump(inv)
        _recompute_kpi_for_room_type(rec["room_type_id"])

    return success(ser_transient_reservation(rec), status=200)


# ----------------------------------------------------------------------------
def _check_los(plan, nights):
    if nights < plan["min_los"] or (plan["max_los"] > 0 and nights > plan["max_los"]):
        raise err(ERR_LOS_VIOLATION, "Stay nights violate the plan's LOS band")


def _night_keys(rec):
    from datetime import datetime, timezone
    start = datetime.strptime(rec["arrival_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(rec["nights"])]


def _inventory_days_for(rec):
    keys = set(_night_keys(rec))
    return [inv for inv in db.inventory_days.values()
            if inv["room_type_id"] == rec["room_type_id"] and inv["stay_date_key"] in keys]


def _require_inventory_days(rec):
    keys = _night_keys(rec)
    found = {}
    for inv in db.inventory_days.values():
        if inv["room_type_id"] == rec["room_type_id"] and inv["stay_date_key"] in keys:
            found[inv["stay_date_key"]] = inv
    for k in keys:
        if k not in found:
            raise err(ERR_MISSING_INVENTORY_DAY, f"No InventoryDay exists for night {k}")
    return [found[k] for k in keys]


def _recompute_kpi_for_room_type(room_type_id):
    rt = db.room_types.get(room_type_id)
    if rt is None:
        return
    prop = db.properties.get(rt["property_id"])
    if prop is not None:
        recompute_property_kpi(prop)
        bump(prop)
