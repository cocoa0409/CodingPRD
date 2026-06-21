"""Existence lookups returning the correct per-type not-found error (PRD §2.6)."""

import errors
from db import db
from errors import err


def get_commissary(cid):
    rec = db.commissaries.get(cid)
    if rec is None:
        raise err(errors.ERR_COMMISSARY_NOT_FOUND, "Commissary not found")
    return rec


def get_truck(tid):
    rec = db.trucks.get(tid)
    if rec is None:
        raise err(errors.ERR_TRUCK_NOT_FOUND, "Truck not found")
    return rec


def get_permit(pid):
    rec = db.permits.get(pid)
    if rec is None:
        raise err(errors.ERR_PERMIT_NOT_FOUND, "Permit not found")
    return rec


def get_spot(sid):
    rec = db.spots.get(sid)
    if rec is None:
        raise err(errors.ERR_SPOT_NOT_FOUND, "Spot not found")
    return rec


def get_event(eid):
    rec = db.events.get(eid)
    if rec is None:
        raise err(errors.ERR_EVENT_NOT_FOUND, "Event not found")
    return rec


def get_booking(bid):
    rec = db.bookings.get(bid)
    if rec is None:
        raise err(errors.ERR_BOOKING_NOT_FOUND, "Booking not found")
    return rec


def get_menu_item(mid):
    rec = db.menu_items.get(mid)
    if rec is None:
        raise err(errors.ERR_MENU_ITEM_NOT_FOUND, "Menu item not found")
    return rec


def get_prep_batch(pbid):
    rec = db.prep_batches.get(pbid)
    if rec is None:
        raise err(errors.ERR_BATCH_NOT_FOUND, "Prep batch not found")
    return rec


def get_staff_shift(sid):
    rec = db.staff_shifts.get(sid)
    if rec is None:
        raise err(errors.ERR_SHIFT_NOT_FOUND, "Staff shift not found")
    return rec


def get_order(oid):
    rec = db.orders.get(oid)
    if rec is None:
        raise err(errors.ERR_ORDER_NOT_FOUND, "Order not found")
    return rec


def get_order_line(lid):
    rec = db.order_lines.get(lid)
    if rec is None:
        raise err(errors.ERR_LINE_NOT_FOUND, "Order line not found")
    return rec


def get_utility_log(lid):
    rec = db.utility_logs.get(lid)
    if rec is None:
        raise err(errors.ERR_LOG_NOT_FOUND, "Utility log not found")
    return rec
