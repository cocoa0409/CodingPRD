from flask import Blueprint, request

import core
from core import (
    db, ok, get_body, req_str, req_datetime, opt_bool, opt_int, fetch,
    authenticate, authorize, require_owner, new_common, touch, serialize,
    sorted_by_created, paginate, parse_iso, iso_from_dt, days_ceil, round_half_up,
    ApiError, MEMBER_DISCOUNT_PCT, MULTI_DAY_THRESHOLD, MULTI_DAY_DISCOUNT_PCT,
    DAMAGE_WAIVER_PCT, LATE_FEE_MULTIPLIER, SERVICE_BUFFER_HOURS, LOYALTY_CENTS_PER_POINT,
    add_loyalty,
)
from decimal import Decimal
from datetime import timedelta

bp = Blueprint("rentals", __name__)

NON_TERMINAL = {"QUOTED", "PICKED_UP"}


def compute_estimated(daily_rate, rental_days, tier, damage_waiver):
    daily_subtotal = daily_rate * rental_days
    if rental_days >= MULTI_DAY_THRESHOLD:
        multi_day_discount = round_half_up(Decimal(daily_subtotal) * MULTI_DAY_DISCOUNT_PCT)
    else:
        multi_day_discount = 0
    discounted = daily_subtotal - multi_day_discount
    member_discount = round_half_up(Decimal(discounted) * MEMBER_DISCOUNT_PCT[tier])
    if damage_waiver:
        waiver_fee = round_half_up(Decimal(daily_subtotal) * DAMAGE_WAIVER_PCT)
    else:
        waiver_fee = 0
    return (discounted - member_discount) + waiver_fee


def _interval(start_at, due_at):
    start = parse_iso(start_at)
    end = parse_iso(due_at) + timedelta(hours=SERVICE_BUFFER_HOURS)
    return start, end


@bp.route("/coop/rental-agreements", methods=["POST"])
def create_rental():
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    data = get_body()
    member_id = req_str(data, "member_id")
    gear_unit_id = req_str(data, "gear_unit_id")
    start_at = req_datetime(data, "start_at")
    due_at = req_datetime(data, "due_at")
    damage_waiver = opt_bool(data, "damage_waiver", False)
    deposit_cents = opt_int(data, "deposit_cents", 0, min_value=0)

    # ownership (priority 2) before existence
    require_owner(role, uid, member_id)

    # existence left-to-right (priority 3): member, then gear_unit
    member = fetch("members", member_id)
    unit = fetch("gear_units", gear_unit_id)
    sku = fetch("gear_skus", unit["gear_sku_id"])

    # business_safety (priority 5)
    if member["membership_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBERSHIP_INACTIVE", "Member is LAPSED; cannot quote a rental")

    # business_temporal (priority 6): half-open overlap incl. service buffer
    req_start, req_end = _interval(start_at, due_at)
    for r in db.rentals.values():
        if r["gear_unit_id"] != gear_unit_id:
            continue
        if r["status"] not in NON_TERMINAL:
            continue
        ex_start, ex_end = _interval(r["start_at"], r["due_at"])
        if max(req_start, ex_start) < min(req_end, ex_end):
            raise ApiError("ERR_UNIT_UNAVAILABLE",
                           "Requested window overlaps an existing rental on this unit")

    # business_referential (priority 7): parent SKU must be rentable
    if not sku["rentable"]:
        raise ApiError("ERR_UNIT_NOT_RENTABLE", "Unit's parent SKU is not rentable")

    rental_days = max(1, days_ceil((parse_iso(due_at) - parse_iso(start_at)).total_seconds()))
    daily_rate = sku["daily_rental_rate_cents"]
    estimated = compute_estimated(daily_rate, rental_days, member["membership_tier"], damage_waiver)

    rental = new_common()
    rental.update({
        "member_id": member_id,
        "gear_unit_id": gear_unit_id,
        "start_at": start_at,
        "due_at": due_at,
        "returned_at": None,
        "status": "QUOTED",
        "daily_rate_cents": daily_rate,
        "rental_days": rental_days,
        "damage_waiver": damage_waiver,
        "deposit_cents": deposit_cents,
        "estimated_charge_cents": estimated,
        "final_charge_cents": None,
    })
    db.rentals[rental["id"]] = rental
    return ok(serialize(rental), status=201)


@bp.route("/coop/rental-agreements/<rid>", methods=["GET"])
def get_rental(rid):
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    rental = fetch("rentals", rid)
    require_owner(role, uid, rental["member_id"])
    return ok(serialize(rental))


@bp.route("/coop/rental-agreements", methods=["GET"])
def list_rentals():
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    member_id = request.args.get("member_id")
    if role == "Member":
        if member_id is not None and member_id != uid:
            raise ApiError("ERR_UNAUTHORIZED", "Members may only list their own rentals")
        member_id = uid
    gear_unit_id = request.args.get("gear_unit_id")
    status = request.args.get("status")
    items = list(db.rentals.values())
    if member_id is not None:
        items = [r for r in items if r["member_id"] == member_id]
    if gear_unit_id is not None:
        items = [r for r in items if r["gear_unit_id"] == gear_unit_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok(page, is_array=True, pagination=meta)


@bp.route("/coop/rental-agreements/<rid>/pickup", methods=["POST"])
def pickup_rental(rid):
    uid, role = authenticate()
    authorize(role, {"StoreStaff"})
    rental = fetch("rentals", rid)
    # state (priority 4)
    if rental["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "Rental is not QUOTED")
    unit = fetch("gear_units", rental["gear_unit_id"])
    if unit["status"] != "AVAILABLE":
        raise ApiError("ERR_UNIT_NOT_READY", "Unit is currently RENTED_OUT")
    # membership (priority 5)
    member = fetch("members", rental["member_id"])
    if member["membership_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBERSHIP_INACTIVE", "Member is LAPSED; cannot pick up")

    rental["status"] = "PICKED_UP"
    touch(rental)
    unit["status"] = "RENTED_OUT"
    touch(unit)
    return ok(serialize(rental))


@bp.route("/coop/rental-agreements/<rid>/return", methods=["POST"])
def return_rental(rid):
    uid, role = authenticate()
    authorize(role, {"StoreStaff"})
    rental = fetch("rentals", rid)
    if rental["status"] != "PICKED_UP":
        raise ApiError("ERR_INVALID_STATE", "Rental is not PICKED_UP")

    returned_dt = db.clock
    due_dt = parse_iso(rental["due_at"])
    if returned_dt > due_dt:
        days_late = days_ceil((returned_dt - due_dt).total_seconds())
        late_fee = round_half_up(
            Decimal(days_late) * Decimal(rental["daily_rate_cents"]) * LATE_FEE_MULTIPLIER
        )
    else:
        late_fee = 0
    final_charge = rental["estimated_charge_cents"] + late_fee

    rental["returned_at"] = iso_from_dt(returned_dt)
    rental["final_charge_cents"] = final_charge
    rental["status"] = "RETURNED"
    touch(rental)

    unit = fetch("gear_units", rental["gear_unit_id"])
    unit["status"] = "AVAILABLE"
    touch(unit)

    member = fetch("members", rental["member_id"])
    add_loyalty(member, final_charge // LOYALTY_CENTS_PER_POINT)
    return ok(serialize(rental))


@bp.route("/coop/rental-agreements/<rid>/cancel", methods=["POST"])
def cancel_rental(rid):
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    rental = fetch("rentals", rid)
    require_owner(role, uid, rental["member_id"])
    if rental["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "Rental is not QUOTED")
    rental["status"] = "CANCELLED"
    touch(rental)
    return ok(serialize(rental))
