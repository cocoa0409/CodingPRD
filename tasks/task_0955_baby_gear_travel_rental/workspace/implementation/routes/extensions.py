from flask import Blueprint

import calc
import services
from db import bump, store
from errors import ApiError
from middleware import require_roles
from response import ok_obj
from serialize import ser_extension
from util import midnight

bp = Blueprint("extensions", __name__)


def _get_extension(eid):
    e = store.extensions.get(eid)
    if e is None:
        raise ApiError("ERR_EXTENSION_NOT_FOUND", 404, "Extension request not found")
    return e


@bp.get("/extensions/<eid>")
def get_extension(eid):
    uid, role = require_roles("Customer", "OperationsAdmin")
    e = _get_extension(eid)
    if role == "Customer":
        res = store.reservations[e["reservation_id"]]
        if res["customer_id"] != uid:
            raise ApiError("ERR_FORBIDDEN", 403, "Not the reservation owner")
    return ok_obj(ser_extension(e))


@bp.post("/extensions/<eid>/approve")
def approve_extension(eid):
    uid, _ = require_roles("OperationsAdmin")
    e = _get_extension(eid)
    if e["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Extension is not PENDING")
    res = store.reservations[e["reservation_id"]]
    if res["status"] not in ("CONFIRMED", "DELIVERED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Reservation must be CONFIRMED or DELIVERED")
    # Temporal sweep: no other reservation's committed interval (buffered,
    # half-open) may overlap [current end_date, requested_end_date) on any
    # allocated unit of this reservation.
    w_start, w_end = midnight(res["end_date"]), midnight(e["requested_end_date"])
    lines = services.lines_of(res["id"])
    for line in lines:
        unit_id = line["assigned_unit_id"]
        if unit_id is None or line["status"] not in ("ALLOCATED", "OUT"):
            continue
        unit = store.units[unit_id]
        if calc.unit_has_committed_overlap(unit, w_start, w_end,
                                           exclude_reservation_id=res["id"]):
            raise ApiError("ERR_EXTENSION_WINDOW_CONFLICT", 409,
                           "Extension window overlaps another reservation's committed interval")
    ext_days = (e["requested_end_date"] - res["end_date"]).days
    charge = calc.extension_charge(lines, ext_days)
    e["extension_charge_cents"] = charge
    e["status"] = "APPROVED"
    e["decided_by_user_id"] = uid
    bump(e)
    res["end_date"] = e["requested_end_date"]
    res["extension_days"] += ext_days
    res["extension_charge_cents"] += charge
    bump(res)
    return ok_obj(ser_extension(e))


@bp.post("/extensions/<eid>/deny")
def deny_extension(eid):
    uid, _ = require_roles("OperationsAdmin")
    e = _get_extension(eid)
    if e["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Extension is not PENDING")
    e["status"] = "DENIED"
    e["decided_by_user_id"] = uid
    bump(e)
    return ok_obj(ser_extension(e))
