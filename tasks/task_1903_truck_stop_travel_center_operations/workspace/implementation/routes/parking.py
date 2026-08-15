"""Parking spaces and paid reservations (PRD 3.5)."""
from datetime import timedelta

from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_MEMBER_NOT_ACTIVE,
    ERR_NOT_FOUND, ERR_NO_POINTS, ERR_PARKING_CAPACITY_FULL,
    ERR_PLATE_NOT_REGISTERED, ERR_SHIFT_NOT_OPEN, ERR_INVALID_WINDOW,
    ERR_FORBIDDEN,
)
from middleware import authorized, scope_member
from response import success_object
from routes.helpers import list_from, list_response, public
from services import loyalty, pricing
from services.core import new_record, stamp, touch, adjust_shift_expected
from util import CLOCK, fmt_dt, parse_dt
from validate import (
    get_body, query_filter, require_path_resource, valid_enum, valid_int,
    valid_nonneg_int, valid_dt, valid_bool, req_str, req_enum, req_dt, req_bool,
)

bp = Blueprint("parking", __name__)

SPACE_TYPES = ["STANDARD", "OVERSIZED"]
RES_STATUSES = ["CONFIRMED", "ACTIVE", "COMPLETED", "CANCELLED", "NO_SHOW"]
READ_ROLES = ["GeneralManager", "ShiftManager", "Cashier"]


# ---------------------------------------------------------------------------
# Spaces
# ---------------------------------------------------------------------------

@bp.post("/sites/<sid>/parking-spaces")
def create_space(sid):
    authorized(["GeneralManager"])
    site = require_path_resource("sites", sid)
    body = get_body()
    space_number = req_str(body, "space_number")
    space_type = req_enum(body, "space_type", SPACE_TYPES)
    if not valid_bool(body.get("is_reservable")):
        raise_error(ERR_INVALID_REQUEST, "is_reservable must be a boolean")
    for sp in db["parking_spaces"].values():
        if sp["site_id"] == site["id"] and sp["space_number"] == space_number:
            raise_error(ERR_INVALID_REQUEST, "space_number must be unique within the site")
    rec = new_record("parking_spaces", {
        "site_id": site["id"],
        "space_number": space_number,
        "space_type": space_type,
        "is_reservable": body["is_reservable"],
        "status": "ACTIVE",
    })
    return success_object(public(rec), status=201)


@bp.get("/sites/<sid>/parking-spaces")
def list_spaces(sid):
    authorized(READ_ROLES)
    require_path_resource("sites", sid)
    filters = {
        "site_id": sid,
        "space_type": query_filter("space_type", SPACE_TYPES),
        "status": query_filter("status", ["ACTIVE", "OUT_OF_SERVICE"]),
    }
    return list_response("parking_spaces", filters)


@bp.get("/parking-spaces/<rid>")
def get_space(rid):
    authorized(READ_ROLES)
    rec = require_path_resource("parking_spaces", rid)
    return success_object(public(rec))


@bp.get("/parking-spaces/<rid>/reservations")
def space_reservations(rid):
    authorized(READ_ROLES)
    space = require_path_resource("parking_spaces", rid)
    res = [r for r in db["parking_reservations"].values() if r["assigned_space_id"] == space["id"]]
    return list_from(res)


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------

def _aggregate_capacity_ok(site, new_from, new_to):
    """At every instant of the new window, overlapping CONFIRMED/ACTIVE count
    must stay strictly below parking_paid_capacity (half-open windows)."""
    capacity = site["parking_paid_capacity"]
    overlapping = []
    for r in db["parking_reservations"].values():
        if r["site_id"] != site["id"] or r["status"] not in ("CONFIRMED", "ACTIVE"):
            continue
        r_from = parse_dt(r["reserved_from"])
        r_to = parse_dt(r["reserved_to"])
        if r_from < new_to and new_from < r_to:  # half-open overlap
            overlapping.append((r_from, r_to))
    instants = {new_from}
    for r_from, _ in overlapping:
        if new_from <= r_from < new_to:
            instants.add(r_from)
    for t in instants:
        count = sum(1 for r_from, r_to in overlapping if r_from <= t < r_to)
        if count + 1 > capacity:
            return False
    return True


@bp.post("/sites/<sid>/parking-reservations")
def create_reservation(sid):
    caller = authorized(["Cashier", "LoyaltyMember"])
    site = require_path_resource("sites", sid)
    body = get_body()

    # Priority 3: members create only for themselves
    if caller.role == "LoyaltyMember":
        scope_member(caller, body.get("loyalty_member_id"))

    # Priority 6: body FK existence
    member = None
    if body.get("loyalty_member_id") is not None:
        member = db["loyalty_members"].get(body["loyalty_member_id"]) \
            if isinstance(body.get("loyalty_member_id"), str) else None
        if member is None:
            raise_error(ERR_NOT_FOUND, "loyalty_member_id does not resolve")

    requested = body.get("requested_redeem_points")
    now = CLOCK.now()

    # p14: reservation creation requires an ACTIVE member
    if member is not None and member["status"] != "ACTIVE":
        raise_error(ERR_MEMBER_NOT_ACTIVE, "loyalty member is not ACTIVE")

    # p17: plate must be a RegisteredVehicle owned by the same member
    plate = body.get("vehicle_plate")
    if member is not None and isinstance(plate, str) and plate:
        owned = any(v["loyalty_member_id"] == member["id"] and v["plate"] == plate
                    for v in db["vehicles"].values())
        if not owned:
            raise_error(ERR_PLATE_NOT_REGISTERED,
                        "vehicle plate is not registered to this member")

    # p19: window shape
    from_raw = body.get("reserved_from")
    to_raw = body.get("reserved_to")
    if valid_dt(from_raw) and valid_dt(to_raw):
        w_from = parse_dt(from_raw)
        w_to = parse_dt(to_raw)
        if w_from < now:
            raise_error(ERR_INVALID_WINDOW, "reserved_from must not be in the past")
        if w_to <= w_from:
            raise_error(ERR_INVALID_WINDOW, "reserved_to must be after reserved_from")
        if w_to - w_from > timedelta(hours=pricing.MAX_WINDOW_HOURS):
            raise_error(ERR_INVALID_WINDOW, "reservation window exceeds 336 hours")
        # p27: aggregate capacity at every instant of the window
        if not _aggregate_capacity_ok(site, w_from, w_to):
            raise_error(ERR_PARKING_CAPACITY_FULL,
                        "overlapping reservation count would exceed parking_paid_capacity")

    # p33: redeemable balance covers requested points
    if member is not None and valid_nonneg_int(requested) and requested > 0:
        if loyalty.redeemable_balance(member["id"], now) < requested:
            raise_error(ERR_NO_POINTS, "requested points exceed the redeemable balance")

    # p41: final shape validation
    if member is None:
        raise_error(ERR_INVALID_REQUEST, "loyalty_member_id is required")
    if not isinstance(plate, str) or not plate:
        raise_error(ERR_INVALID_REQUEST, "vehicle_plate is required")
    # plate ownership is enforced above once shape is known; re-check when it
    # could not be evaluated earlier because the member was missing
    owned = any(v["loyalty_member_id"] == member["id"] and v["plate"] == plate
                for v in db["vehicles"].values())
    if not owned:
        raise_error(ERR_PLATE_NOT_REGISTERED, "vehicle plate is not registered to this member")
    space_type = req_enum(body, "space_type", SPACE_TYPES)
    if not valid_dt(from_raw) or not valid_dt(to_raw):
        raise_error(ERR_INVALID_REQUEST, "reserved_from/reserved_to must be ISO 8601 datetimes")
    if requested is not None and not valid_nonneg_int(requested):
        raise_error(ERR_INVALID_REQUEST, "requested_redeem_points must be a non-negative integer")
    requested = 0 if requested is None else requested

    w_from = parse_dt(from_raw)
    w_to = parse_dt(to_raw)
    points_capped = pricing.capped_points(requested, member)
    charges = pricing.parking_charges(w_from, w_to, space_type, points_capped)
    if points_capped > 0:
        loyalty.burn_fefo(member["id"], points_capped)

    rec = new_record("parking_reservations", {
        "site_id": site["id"],
        "loyalty_member_id": member["id"],
        "vehicle_plate": plate,
        "space_type": space_type,
        "reserved_from": fmt_dt(w_from),
        "reserved_to": fmt_dt(w_to),
        "requested_redeem_points": requested,
        "status": "CONFIRMED",
        "payment_status": "UNPAID",
        "paid_minutes": charges["paid_minutes"],
        "billed_hours": charges["billed_hours"],
        "oversize_fee_cents": charges["oversize_fee_cents"],
        "points_discount_cents": charges["points_discount_cents"],
        "amount_cents": charges["amount_cents"],
        "assigned_space_id": None,
        "shift_id": None,
        "checked_in_at": None,
        "checked_out_at": None,
        "_points_burned": points_capped,
        "_pay_tender": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/sites/<sid>/parking-reservations")
def list_reservations(sid):
    authorized(READ_ROLES)
    require_path_resource("sites", sid)
    filters = {
        "site_id": sid,
        "status": query_filter("status", RES_STATUSES),
        "loyalty_member_id": query_filter("loyalty_member_id"),
    }
    return list_response("parking_reservations", filters)


@bp.get("/parking-reservations/<rid>")
def get_reservation(rid):
    caller = authorized(READ_ROLES + ["LoyaltyMember"])
    rec = require_path_resource("parking_reservations", rid)
    scope_member(caller, rec["loyalty_member_id"])
    return success_object(public(rec))


@bp.post("/parking-reservations/<rid>/check-in")
def check_in(rid):
    authorized(["Cashier"])
    res = require_path_resource("parking_reservations", rid)
    body = get_body()

    # p6: shift FK existence
    shift = None
    if body.get("shift_id") is not None:
        shift = db["shifts"].get(body["shift_id"]) if isinstance(body.get("shift_id"), str) else None
        if shift is None:
            raise_error(ERR_NOT_FOUND, "shift_id does not resolve")

    # p7: transition must exist
    if res["status"] != "CONFIRMED":
        raise_error(ERR_INVALID_STATE, "reservation is not CONFIRMED")
    if res["payment_status"] != "UNPAID":
        raise_error(ERR_INVALID_STATE, "reservation payment must be UNPAID at check-in")
    now = CLOCK.now()
    if not (parse_dt(res["reserved_from"]) <= now
            <= parse_dt(res["reserved_from"]) + timedelta(hours=pricing.NO_SHOW_GRACE_HOURS)):
        raise_error(ERR_INVALID_STATE, "outside the check-in window (reserved_from + 2 hours)")

    # p9: CASH tender requires an OPEN shift
    tender = body.get("tender_type")
    if tender == "CASH" and shift is not None and shift["status"] != "OPEN":
        raise_error(ERR_SHIFT_NOT_OPEN, "cash check-in requires an OPEN shift")

    # p27: space assignment pool
    site = db["sites"].get(res["site_id"])
    eligible = []
    for sp in db["parking_spaces"].values():
        if sp["site_id"] != res["site_id"] or sp["space_type"] != res["space_type"]:
            continue
        if sp["status"] != "ACTIVE" or not sp["is_reservable"]:
            continue
        occupied = any(r["assigned_space_id"] == sp["id"] and r["status"] == "ACTIVE"
                       for r in db["parking_reservations"].values())
        if not occupied:
            eligible.append(sp)
    eligible.sort(key=lambda sp: sp["space_number"])
    if not eligible:
        raise_error(ERR_PARKING_CAPACITY_FULL, "no assignable parking space")

    # p41: final shape validation
    tender = req_enum(body, "tender_type", ["CASH", "CARD"])
    if shift is None:
        raise_error(ERR_INVALID_REQUEST, "shift_id is required")

    res["assigned_space_id"] = eligible[0]["id"]
    res["shift_id"] = shift["id"]
    stamp(res, "checked_in_at")
    res["_pay_tender"] = tender
    res["payment_status"] = "PAID"
    res["status"] = "ACTIVE"
    if tender == "CASH":
        adjust_shift_expected(shift, res["amount_cents"])
    member = db["loyalty_members"].get(res["loyalty_member_id"])
    earned = loyalty.earn_points_for(member, res["amount_cents"], "PARKING", res["id"])
    res["_points_earned"] = earned
    touch(res)
    return success_object(public(res))


@bp.post("/parking-reservations/<rid>/check-out")
def check_out(rid):
    authorized(["Cashier"])
    res = require_path_resource("parking_reservations", rid)
    if res["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "reservation is not ACTIVE")
    res["status"] = "COMPLETED"
    stamp(res, "checked_out_at")
    touch(res)
    return success_object(public(res))


@bp.post("/parking-reservations/<rid>/cancel")
def cancel_reservation(rid):
    caller = authorized(["Cashier", "LoyaltyMember"])
    res = require_path_resource("parking_reservations", rid)
    scope_member(caller, res["loyalty_member_id"])

    if res["status"] == "CONFIRMED":
        if res["payment_status"] != "UNPAID":
            raise_error(ERR_INVALID_STATE, "confirmed reservation must be UNPAID to cancel")
        res["status"] = "CANCELLED"
        if res.get("_points_burned"):
            loyalty.grant_lot(res["loyalty_member_id"], res["_points_burned"],
                              "ADJUSTMENT", res["id"])
        touch(res)
        return success_object(public(res))

    if res["status"] == "ACTIVE":
        if caller.role == "LoyaltyMember":
            raise_error(ERR_FORBIDDEN, "early-departure cancel is a cashier action")
        if res["payment_status"] != "PAID":
            raise_error(ERR_INVALID_STATE, "active reservation must be PAID to cancel")
        res["status"] = "CANCELLED"
        res["payment_status"] = "REFUNDED"
        if res.get("_pay_tender") == "CASH" and res.get("shift_id"):
            shift = db["shifts"].get(res["shift_id"])
            if shift is not None:
                adjust_shift_expected(shift, -res["amount_cents"])
        if res.get("_points_earned"):
            loyalty.clawback_newest(res["loyalty_member_id"], res["_points_earned"],
                                    "ADJUSTMENT", res["id"])
        touch(res)
        return success_object(public(res))

    raise_error(ERR_INVALID_STATE, "reservation cannot be cancelled from its current state")


@bp.post("/parking-reservations/<rid>/no-show")
def no_show(rid):
    authorized(["Cashier", "ShiftManager"])
    res = require_path_resource("parking_reservations", rid)
    if res["status"] != "CONFIRMED":
        raise_error(ERR_INVALID_STATE, "reservation is not CONFIRMED")
    now = CLOCK.now()
    if not now > parse_dt(res["reserved_from"]) + timedelta(hours=pricing.NO_SHOW_GRACE_HOURS):
        raise_error(ERR_INVALID_STATE, "no-show requires the clock past reserved_from + 2 hours")
    res["status"] = "NO_SHOW"
    touch(res)
    return success_object(public(res))
