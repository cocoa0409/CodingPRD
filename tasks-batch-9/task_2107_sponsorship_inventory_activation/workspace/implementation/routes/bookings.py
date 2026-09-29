"""Asset bookings: scheduling geometry, cancellation and delivery
(PRD 3.6, 3.8)."""

from decimal import Decimal

from flask import Blueprint, request

import db
from db import store, new_row, touch, ordered
from errors import ApiError
from middleware import endpoint
from response import ok, created, paginate
from services.cascade import (rollup_entitlement, rollup_contract, rollup_property,
                              release_assignments, release_asset_units)
from services.serialize import booking_out
from routes.entitlements import get_entitlement_or_404
from routes.inventory_assets import get_asset_or_404
from util import body_of, v_str, v_int, v_dt, v_pagination, v_query_enum, gap_minutes

bp = Blueprint("bookings", __name__)

BOOKING_STATUSES = {"SCHEDULED", "DELIVERED", "CANCELLED", "PREEMPTED"}
READ_ROLES = ["PropertyAdmin", "ContractApprover", "ActivationManager", "PerformanceAuditor"]


def get_booking_or_404(booking_id):
    booking = store.bookings.get(booking_id)
    if booking is None:
        raise ApiError("ERR_BOOKING_NOT_FOUND", 404)
    return booking


def _intersects(a_start, a_end, b_start, b_end):
    """Half-open [start, end): touching endpoints do not intersect."""
    return a_start < b_end and b_start < a_end


@bp.post("/asset-bookings")
@endpoint(["ActivationManager"])
def create_booking():
    body = body_of(request)
    entitlement_id = v_str(body, "entitlement_id", min_len=1)
    inventory_asset_id = v_str(body, "inventory_asset_id", min_len=1)
    window_start_raw, window_start = v_dt(body, "window_start")
    window_end_raw, window_end = v_dt(body, "window_end")
    units_booked = v_int(body, "units_booked", min_v=1)
    expected_version = v_int(body, "expected_inventory_asset_version")

    ent = get_entitlement_or_404(entitlement_id)
    asset = get_asset_or_404(inventory_asset_id)

    contract = db.contract_of_entitlement(ent)
    if contract is None or contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409)
    if asset["status"] != "AVAILABLE":
        raise ApiError("ERR_ASSET_UNAVAILABLE", 409)

    if expected_version != asset["version"]:
        raise ApiError("ERR_ASSET_VERSION_STALE", 412)

    if inventory_asset_id != ent["inventory_asset_id"]:
        raise ApiError("ERR_ASSET_MISMATCH", 409)

    if window_end <= window_start:
        raise ApiError("ERR_INVALID_WINDOW", 422)
    if window_start < contract["_term_start_dt"] or window_end > contract["_term_end_dt"]:
        raise ApiError("ERR_WINDOW_OUTSIDE_TERM", 409)

    neighbours = [b for b in db.bookings_of_asset(asset["id"])
                  if b["status"] in ("SCHEDULED", "DELIVERED")]

    # changeover buffer — non-intersecting neighbours of a different contract
    buffer_minutes = asset["changeover_buffer_minutes"]
    for other in neighbours:
        o_start = other["_window_start_dt"]
        o_end = other["_window_end_dt"]
        if _intersects(window_start, window_end, o_start, o_end):
            continue
        other_contract = db.contract_of_booking(other)
        if other_contract is not None and other_contract["id"] == contract["id"]:
            continue
        if window_start >= o_end:
            gap = gap_minutes(o_end, window_start)
        else:
            gap = gap_minutes(window_end, o_start)
        if gap < Decimal(buffer_minutes):
            raise ApiError("ERR_BOOKING_WINDOW_CONFLICT", 409)

    # capacity — intersecting neighbours only
    occupied = 0
    for other in neighbours:
        if _intersects(window_start, window_end, other["_window_start_dt"], other["_window_end_dt"]):
            occupied += other["units_booked"]
    if occupied + units_booked > asset["capacity_units"]:
        raise ApiError("ERR_ASSET_CAPACITY_EXCEEDED", 409)

    row = new_row()
    row.update({
        "entitlement_id": ent["id"],
        "inventory_asset_id": asset["id"],
        "window_start": window_start_raw,
        "_window_start_dt": window_start,
        "window_end": window_end_raw,
        "_window_end_dt": window_end,
        "units_booked": units_booked,
        "status": "SCHEDULED",
        "proof_state": "NONE",
        "verified_impressions": 0,
        "delivered_at": None,
    })
    store.bookings[row["id"]] = row

    asset["reserved_units_total"] = asset["reserved_units_total"] + units_booked
    touch(asset)
    return created(booking_out(row))


@bp.get("/asset-bookings/<booking_id>")
@endpoint(READ_ROLES)
def read_booking(booking_id):
    return ok(booking_out(get_booking_or_404(booking_id)))


@bp.get("/asset-bookings")
@endpoint(READ_ROLES)
def list_bookings():
    status = v_query_enum(request, "status", BOOKING_STATUSES)
    limit, offset = v_pagination(request)
    entitlement_id = request.args.get("entitlement_id")
    inventory_asset_id = request.args.get("inventory_asset_id")

    rows = list(store.bookings.values())
    if entitlement_id is not None:
        rows = [r for r in rows if r["entitlement_id"] == entitlement_id]
    if inventory_asset_id is not None:
        rows = [r for r in rows if r["inventory_asset_id"] == inventory_asset_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(ordered(rows), limit, offset, booking_out)


@bp.post("/asset-bookings/<booking_id>/cancel")
@endpoint(["ActivationManager"])
def cancel_booking(booking_id):
    booking = get_booking_or_404(booking_id)
    body = body_of(request)
    v_str(body, "reason", required=False)

    if booking["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409)
    contract = db.contract_of_booking(booking)
    if contract is None or contract["status"] not in ("COUNTERSIGNED", "ACTIVE"):
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409)

    booking["status"] = "CANCELLED"
    touch(booking)
    release_asset_units(booking)
    release_assignments(booking)
    return ok(booking_out(booking))


@bp.post("/asset-bookings/<booking_id>/deliver")
@endpoint(["ActivationManager"])
def deliver_booking(booking_id):
    booking = get_booking_or_404(booking_id)

    if booking["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409)
    ent = store.entitlements.get(booking["entitlement_id"])
    contract = db.contract_of_booking(booking)
    if contract is None or contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409)
    if store.now() < booking["_window_end_dt"]:
        raise ApiError("ERR_DELIVERY_WINDOW_OPEN", 409)
    asset = store.inventory_assets.get(booking["inventory_asset_id"])
    if asset is not None and asset["requires_staffing"]:
        checked_in = len([a for a in db.assignments_of_booking(booking["id"])
                          if a["status"] == "CHECKED_IN"])
        if checked_in < asset["min_staff_count"]:
            raise ApiError("ERR_STAFFING_INCOMPLETE", 409)

    booking["status"] = "DELIVERED"
    booking["delivered_at"] = store.now_raw()
    touch(booking)

    # still-ASSIGNED shifts become NO_SHOW; CHECKED_IN shifts become RELEASED
    release_assignments(booking, assigned_to="NO_SHOW", checked_in_to="RELEASED")
    release_asset_units(booking)

    if ent is not None:
        rollup_entitlement(ent)
    rollup_contract(contract)
    prop = store.properties.get(contract["property_id"])
    if prop is not None:
        rollup_property(prop)
    return ok(booking_out(booking))
