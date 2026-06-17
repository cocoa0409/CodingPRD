"""Amenity-request routes (PRD §3.5). Lines attach to a reservation and drive
the parallel billing dimension."""
from __future__ import annotations

from flask import Blueprint, g

import db
from errors import (
    APIError,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_AMENITY_LOCKED,
)
from middleware import require_role, current_user_id
from response import ok_object, ok_array
from routes._helpers import (
    parse_pagination, paginate, order_by_created, get_body,
    require_str, require_int, get_reservation, get_amenity,
)
from services.common import stamp_new, touch, public, public_list
from services import state_machines as sm

bp = Blueprint("amenities", __name__)


@bp.post("/workplace/reservations/<rid>/amenities")
def add_amenity(rid):
    require_role("Employee")
    r = get_reservation(rid)
    # ownership: parent reservation's employee_id == X-User-ID
    if r["employee_id"] != current_user_id():
        raise APIError(ERR_FORBIDDEN, 403, "Caller does not own this reservation")
    body = get_body()
    amenity_code = require_str(body, "amenity_code")
    unit_price_cents = require_int(body, "unit_price_cents", minimum=0)
    quantity = require_int(body, "quantity", minimum=1)
    # state: adding a line permitted only while occupancy in {BOOKED, CHECKED_IN}
    if r["occupancy_status"] not in ("BOOKED", "CHECKED_IN"):
        raise APIError(ERR_INVALID_STATE, 409, "Reservation not open for amenities")

    line = {
        "reservation_id": r["id"],
        "amenity_code": amenity_code,
        "unit_price_cents": unit_price_cents,
        "quantity": quantity,
        "line_status": "REQUESTED",
        "line_total_cents": unit_price_cents * quantity,
    }
    stamp_new(line)
    db.amenity_requests[line["id"]] = line

    # NONE -> PROVISIONAL on first line; recompute provisional either way.
    if r["billing_status"] == "NONE":
        r["billing_status"] = "PROVISIONAL"
    sm.reconcile_provisional(r)
    return ok_object(public(line), 201)


@bp.get("/workplace/reservations/<rid>/amenities")
def list_amenities(rid):
    require_role("FacilityManager", "Analyst", "Employee")
    r = get_reservation(rid)
    if g.user_role == "Employee" and r["employee_id"] != current_user_id():
        raise APIError(ERR_FORBIDDEN, 403, "Caller does not own this reservation")
    limit, offset = parse_pagination()
    items = [a for a in db.amenity_requests.values() if a["reservation_id"] == r["id"]]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(public_list(page), limit, offset, total)


@bp.get("/workplace/amenity-requests/<aid>")
def get_amenity_ep(aid):
    require_role("FacilityManager", "Analyst", "Employee")
    a = get_amenity(aid)
    if g.user_role == "Employee":
        r = db.reservations.get(a["reservation_id"])
        if r is not None and r["employee_id"] != current_user_id():
            raise APIError(ERR_FORBIDDEN, 403, "Caller does not own this amenity")
    return ok_object(public(a))


@bp.post("/workplace/amenity-requests/<aid>/approve")
def approve_amenity(aid):
    require_role("FacilityManager")
    a = get_amenity(aid)
    if a["line_status"] != "REQUESTED":
        raise APIError(ERR_INVALID_STATE, 409, "Amenity not REQUESTED")
    r = db.reservations.get(a["reservation_id"])
    if r is not None and r["occupancy_status"] not in ("BOOKED", "CHECKED_IN"):
        raise APIError(ERR_INVALID_STATE, 409, "Parent reservation not open")
    a["line_status"] = "APPROVED"
    touch(a)
    if r is not None:
        sm.reconcile_provisional(r)
    return ok_object(public(a))


@bp.post("/workplace/amenity-requests/<aid>/deny")
def deny_amenity(aid):
    require_role("FacilityManager")
    a = get_amenity(aid)
    if a["line_status"] != "REQUESTED":
        raise APIError(ERR_INVALID_STATE, 409, "Amenity not REQUESTED")
    a["line_status"] = "DENIED"
    touch(a)
    r = db.reservations.get(a["reservation_id"])
    if r is not None:
        sm.reconcile_provisional(r)
    return ok_object(public(a))


@bp.post("/workplace/amenity-requests/<aid>/cancel")
def cancel_amenity(aid):
    require_role("Employee")
    a = get_amenity(aid)
    r = db.reservations.get(a["reservation_id"])
    # ownership: parent reservation's employee_id == X-User-ID
    if r is not None and r["employee_id"] != current_user_id():
        raise APIError(ERR_FORBIDDEN, 403, "Caller does not own this amenity")
    # state: cancel allowed from REQUESTED or APPROVED
    if a["line_status"] not in ("REQUESTED", "APPROVED"):
        raise APIError(ERR_INVALID_STATE, 409, "Amenity not cancellable")
    # cancelling an APPROVED line is forbidden once parent reservation COMPLETED
    if a["line_status"] == "APPROVED" and r is not None and r["occupancy_status"] == "COMPLETED":
        raise APIError(ERR_AMENITY_LOCKED, 409, "Chargeback frozen; cannot cancel")
    a["line_status"] = "CANCELLED"
    touch(a)
    if r is not None:
        sm.reconcile_provisional(r)
    return ok_object(public(a))
