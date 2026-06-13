"""Reservation routes — create, lifecycle, deposit holds, special requests
(PRD §3.3–§3.7)."""
from flask import Blueprint, request

import clock
import db
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_NOT_RESOURCE_OWNER,
    ERR_CUSTOMER_BLOCKED, ERR_RESTAURANT_CLOSED, ERR_DEPOSIT_REQUIRED,
    ERR_NO_SHOW_TOO_EARLY, ERR_RESCHEDULE_TOO_LATE, ERR_DUPLICATE_DEPOSIT_HOLD,
    ERR_VALIDATION,
)
from middleware import require_roles
from response import object_response, array_response
from services import calc, booking
from services.lookup import get_or_404
from services.notifications import create_notification
from services.cascades import (
    accrue_failure_and_maybe_block, recompute_reliability,
    run_table_freeing_cascade,
)
from timeutil import parse_iso
from validators import (
    get_body, require_str, require_int, require_enum, require_last4,
    paginate,
)
from datetime import timedelta

bp = Blueprint("reservations", __name__)


def _held_hold(reservation_id):
    for h in db.deposit_holds.values():
        if h["reservation_id"] == reservation_id and h["status"] == "HELD":
            return h
    return None


# ---- create ------------------------------------------------------------------

@bp.post("/reservations")
def create_reservation():
    user_id, role = require_roles({"Customer", "Host"})
    body = get_body()
    # existence of FKs, left-to-right (restaurant, customer, table)
    restaurant_id = require_str(body, "restaurant_id")
    customer_id = require_str(body, "customer_id")
    table_id = require_str(body, "table_id")
    expected_version = require_int(body, "expected_table_version")
    party_size = require_int(body, "party_size", minimum=1)
    reservation_start = parse_iso(require_str(body, "reservation_start"), "reservation_start")

    restaurant = db.restaurants.get(restaurant_id)
    if restaurant is None:
        raise err(ERR_NOT_FOUND, "restaurant not found")
    customer = db.customers.get(customer_id)
    if customer is None:
        raise err(ERR_NOT_FOUND, "customer not found")
    table = db.tables.get(table_id)
    if table is None:
        raise err(ERR_NOT_FOUND, "table not found")

    # No ownership check on create: PRD §2.1 limits ERR_NOT_RESOURCE_OWNER to
    # cancel / reschedule / waitlist-cancel only.

    # blocked-customer safety (the referenced customer)
    if customer["status"] == "BLOCKED":
        raise err(ERR_CUSTOMER_BLOCKED, "customer is blocked")

    # restaurant open
    if restaurant["status"] != "OPEN":
        raise err(ERR_RESTAURANT_CLOSED, "restaurant is closed")

    # party-size match
    booking.check_party_size(table, party_size)
    # service-period + slot grid
    sp = booking.matching_service_period(restaurant, reservation_start)
    # compute window for overlap / buyout / pacing checks
    turn_window_end, release_at = calc.reservation_turn_window(
        reservation_start, table, restaurant)
    # table overlap
    booking.check_table_overlap(table_id, reservation_start, release_at)
    # area buyout
    booking.check_area_buyout(table, reservation_start, release_at)
    # pacing
    booking.check_pacing(restaurant, sp, reservation_start, party_size)
    # OCC
    booking.check_occ(table, expected_version)

    rec = db.base_fields()
    rec.update({
        "restaurant_id": restaurant_id,
        "customer_id": customer_id,
        "table_id": table_id,
        "expected_table_version": expected_version,
        "party_size": party_size,
        "reservation_start": reservation_start,
        "turn_window_end": turn_window_end,
        "release_at": release_at,
        "deposit_required": party_size >= restaurant["deposit_required_party_threshold"],
        "cancellation_fee_cents": 0,
        "status": "REQUESTED",
    })
    db.reservations[rec["id"]] = rec
    # creating the reservation bumps the target table's version
    db.touch(table)
    return object_response(db.serialize(rec), 201)


# ---- reads -------------------------------------------------------------------

@bp.get("/reservations/<rid>")
def read_reservation(rid):
    require_roles({"Manager", "Host", "Customer"})
    rec = get_or_404(db.reservations, rid)
    return object_response(db.serialize(rec), 200)


@bp.get("/reservations")
def list_reservations():
    require_roles({"Manager", "Host", "Customer"})
    a = request.args
    restaurant_id = a.get("restaurant_id")
    customer_id = a.get("customer_id")
    table_id = a.get("table_id")
    status = a.get("status")
    records = []
    for r in db.reservations.values():
        if restaurant_id is not None and r["restaurant_id"] != restaurant_id:
            continue
        if customer_id is not None and r["customer_id"] != customer_id:
            continue
        if table_id is not None and r["table_id"] != table_id:
            continue
        if status is not None and r["status"] != status:
            continue
        records.append(r)
    page, pagination = paginate(records)
    return array_response([db.serialize(r) for r in page], pagination, 200)


# ---- deposit hold placement --------------------------------------------------

@bp.post("/reservations/<rid>/deposit-holds")
def place_deposit_hold(rid):
    require_roles({"Customer", "Host"})
    res = get_or_404(db.reservations, rid)
    body = get_body()
    card_last4 = require_last4(body, "card_last4")
    # no second hold while one is neither RELEASED nor EXPIRED
    for h in db.deposit_holds.values():
        if h["reservation_id"] == rid and h["status"] not in ("RELEASED", "EXPIRED"):
            raise err(ERR_DUPLICATE_DEPOSIT_HOLD, "reservation already has an active hold")
    restaurant = db.restaurants[res["restaurant_id"]]
    amount = calc.standard_deposit(restaurant, res["party_size"])

    rec = db.base_fields()
    rec.update({
        "reservation_id": rid,
        "amount_cents": amount,
        "captured_cents": 0,
        "card_last4": card_last4,
        "status": "HELD",
    })
    db.deposit_holds[rec["id"]] = rec
    return object_response(db.serialize(rec), 201)


# ---- confirm -----------------------------------------------------------------

@bp.post("/reservations/<rid>/confirm")
def confirm_reservation(rid):
    require_roles({"Host"})
    res = get_or_404(db.reservations, rid)
    if res["status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "reservation is not REQUESTED")
    customer = db.customers[res["customer_id"]]
    # blocked-customer safety (confirm is a guarded operation)
    if customer["status"] == "BLOCKED":
        raise err(ERR_CUSTOMER_BLOCKED, "customer is blocked")
    # table present and not OUT_OF_SERVICE
    table = db.tables.get(res["table_id"]) if res["table_id"] else None
    if table is None or table["status"] == "OUT_OF_SERVICE":
        raise err(ERR_INVALID_STATE, "table is unavailable for confirmation")
    # deposit required -> must have a HELD hold
    if res["deposit_required"] and _held_hold(rid) is None:
        raise err(ERR_DEPOSIT_REQUIRED, "deposit hold required before confirm")

    res["status"] = "CONFIRMED"
    db.touch(res)
    create_notification("RESERVATION", rid, "RESERVATION_CONFIRMED", customer["phone"])
    return object_response(db.serialize(res), 200)


# ---- reschedule --------------------------------------------------------------

@bp.post("/reservations/<rid>/reschedule")
def reschedule_reservation(rid):
    user_id, role = require_roles({"Customer", "Host"})
    res = get_or_404(db.reservations, rid)
    if res["status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "reservation is not CONFIRMED")
    if role == "Customer" and res["customer_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "not the resource owner")

    body = get_body()
    table_id = require_str(body, "table_id")
    expected_version = require_int(body, "expected_table_version")
    reservation_start = parse_iso(require_str(body, "reservation_start"), "reservation_start")
    table = db.tables.get(table_id)
    if table is None:
        raise err(ERR_NOT_FOUND, "table not found")

    restaurant = db.restaurants[res["restaurant_id"]]
    # reschedule allowed only strictly before (start - late_cancel_cutoff_hours)
    now = clock.now()
    cutoff_instant = res["reservation_start"] - timedelta(hours=restaurant["late_cancel_cutoff_hours"])
    if not (now < cutoff_instant):
        raise err(ERR_RESCHEDULE_TOO_LATE, "reschedule attempted at or after the cutoff")

    # re-run booking checks for the (possibly new) start/table
    booking.check_party_size(table, res["party_size"])
    sp = booking.matching_service_period(restaurant, reservation_start)
    turn_window_end, release_at = calc.reservation_turn_window(
        reservation_start, table, restaurant)
    booking.check_table_overlap(table_id, reservation_start, release_at,
                                exclude_reservation_id=rid)
    booking.check_area_buyout(table, reservation_start, release_at)
    booking.check_pacing(restaurant, sp, reservation_start, res["party_size"],
                         exclude_reservation_id=rid)
    booking.check_occ(table, expected_version)

    res["table_id"] = table_id
    res["expected_table_version"] = expected_version
    res["reservation_start"] = reservation_start
    res["turn_window_end"] = turn_window_end
    res["release_at"] = release_at
    res["status"] = "REQUESTED"
    db.touch(res)
    db.touch(table)
    return object_response(db.serialize(res), 200)


# ---- cancel ------------------------------------------------------------------

@bp.post("/reservations/<rid>/cancel")
def cancel_reservation(rid):
    user_id, role = require_roles({"Customer", "Host"})
    res = get_or_404(db.reservations, rid)
    if res["status"] not in ("REQUESTED", "CONFIRMED"):
        raise err(ERR_INVALID_STATE, "reservation is not cancellable")
    if role == "Customer" and res["customer_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "not the resource owner")

    restaurant = db.restaurants[res["restaurant_id"]]
    customer = db.customers[res["customer_id"]]
    was_confirmed = res["status"] == "CONFIRMED"
    hold = _held_hold(rid)

    if was_confirmed:
        fee = calc.cancellation_fee(
            res["reservation_start"], clock.now(), res["party_size"],
            restaurant["per_seat_deposit_cents"], restaurant["late_cancel_cutoff_hours"],
            variant="late_cancel",
            hold_amount_cents=hold["amount_cents"] if hold else None,
        )
    else:
        # REQUESTED cancel: treated as early -> no fee
        fee = 0

    res["cancellation_fee_cents"] = fee
    if hold is not None:
        if fee > 0:
            hold["captured_cents"] = fee
            hold["status"] = "CAPTURED"
        else:
            hold["captured_cents"] = 0
            hold["status"] = "RELEASED"
        db.touch(hold)

    res["status"] = "CANCELLED"
    db.touch(res)

    if fee > 0:
        accrue_failure_and_maybe_block(customer, restaurant)

    # free the table's future slot -> table-freeing cascade unless SEATED
    table = db.tables.get(res["table_id"]) if res["table_id"] else None
    if not (table is not None and table["status"] == "SEATED"):
        run_table_freeing_cascade(res["restaurant_id"])

    return object_response(db.serialize(res), 200)


# ---- seat --------------------------------------------------------------------

@bp.post("/reservations/<rid>/seat")
def seat_reservation(rid):
    require_roles({"Host"})
    res = get_or_404(db.reservations, rid)
    if res["status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "reservation is not CONFIRMED")
    table = db.tables.get(res["table_id"]) if res["table_id"] else None
    if table is None or table["status"] not in ("AVAILABLE", "DIRTY"):
        raise err(ERR_INVALID_STATE, "table is not seatable")
    res["status"] = "SEATED"
    db.touch(res)
    table["status"] = "SEATED"
    db.touch(table)
    return object_response(db.serialize(res), 200)


# ---- no-show -----------------------------------------------------------------

@bp.post("/reservations/<rid>/no-show")
def no_show_reservation(rid):
    require_roles({"Host"})
    res = get_or_404(db.reservations, rid)
    if res["status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "reservation is not CONFIRMED")
    grace_instant = res["reservation_start"] + timedelta(minutes=calc.NO_SHOW_GRACE_MINUTES)
    if clock.now() < grace_instant:
        raise err(ERR_NO_SHOW_TOO_EARLY, "no-show marked before grace window")

    restaurant = db.restaurants[res["restaurant_id"]]
    customer = db.customers[res["customer_id"]]
    hold = _held_hold(rid)
    fee = calc.cancellation_fee(
        res["reservation_start"], clock.now(), res["party_size"],
        restaurant["per_seat_deposit_cents"], restaurant["late_cancel_cutoff_hours"],
        variant="no_show",
        hold_amount_cents=hold["amount_cents"] if hold else None,
    )
    res["cancellation_fee_cents"] = fee
    if hold is not None:
        hold["captured_cents"] = fee
        hold["status"] = "CAPTURED"
        db.touch(hold)
    accrue_failure_and_maybe_block(customer, restaurant)
    create_notification("RESERVATION", rid, "NO_SHOW_FEE_CHARGED", customer["phone"])
    res["status"] = "NO_SHOW"
    db.touch(res)
    return object_response(db.serialize(res), 200)


# ---- complete ----------------------------------------------------------------

@bp.post("/reservations/<rid>/complete")
def complete_reservation(rid):
    require_roles({"Host"})
    res = get_or_404(db.reservations, rid)
    if res["status"] != "SEATED":
        raise err(ERR_INVALID_STATE, "reservation is not SEATED")
    customer = db.customers[res["customer_id"]]
    res["status"] = "COMPLETED"
    db.touch(res)
    customer["lifetime_reservations"] += 1
    recompute_reliability(customer)
    db.touch(customer)
    table = db.tables.get(res["table_id"]) if res["table_id"] else None
    if table is not None:
        table["status"] = "DIRTY"
        db.touch(table)
    hold = _held_hold(rid)
    if hold is not None:
        hold["captured_cents"] = 0
        hold["status"] = "RELEASED"
        db.touch(hold)
    return object_response(db.serialize(res), 200)


# ---- special requests --------------------------------------------------------

@bp.post("/reservations/<rid>/special-requests")
def create_special_request(rid):
    require_roles({"Customer", "Host"})
    res = get_or_404(db.reservations, rid)
    body = get_body()
    category = require_enum(body, "category",
                            {"DIETARY", "SEATING", "OCCASION", "ACCESSIBILITY", "OTHER"})
    note = require_str(body, "note", max_len=500)

    rec = db.base_fields(versioned=False)
    rec.update({
        "reservation_id": rid,
        "category": category,
        "note": note,
        "acknowledged": False,
    })
    db.special_requests[rec["id"]] = rec
    return object_response(db.serialize(rec), 201)


@bp.get("/reservations/<rid>/special-requests")
def list_special_requests(rid):
    require_roles({"Manager", "Host", "Customer"})
    get_or_404(db.reservations, rid)
    records = [s for s in db.special_requests.values() if s["reservation_id"] == rid]
    page, pagination = paginate(records)
    return array_response([db.serialize(r) for r in page], pagination, 200)
