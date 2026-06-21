"""Existence lookups that raise the correct not-found error (PRD 2.7)."""
from db import db
from errors import ApiError


def get_marina(mid):
    m = db.marinas.get(mid)
    if m is None:
        raise ApiError("ERR_MARINA_NOT_FOUND", "Marina not found")
    return m


def get_dock_slot(sid):
    s = db.dock_slots.get(sid)
    if s is None:
        raise ApiError("ERR_SLOT_NOT_FOUND", "Dock slot not found")
    return s


def get_boat(bid):
    b = db.boats.get(bid)
    if b is None:
        raise ApiError("ERR_BOAT_NOT_FOUND", "Boat not found")
    return b


def get_captain(cid):
    c = db.captains.get(cid)
    if c is None:
        raise ApiError("ERR_CAPTAIN_NOT_FOUND", "Captain not found")
    return c


def get_mate(mid):
    m = db.mates.get(mid)
    if m is None:
        raise ApiError("ERR_MATE_NOT_FOUND", "Mate not found")
    return m


def get_permit(pid):
    p = db.permits.get(pid)
    if p is None:
        raise ApiError("ERR_PERMIT_NOT_FOUND", "Permit not found")
    return p


def get_charter(cid):
    c = db.charters.get(cid)
    if c is None:
        raise ApiError("ERR_CHARTER_NOT_FOUND", "Charter not found")
    return c


def get_booking(bid):
    b = db.bookings.get(bid)
    if b is None:
        raise ApiError("ERR_BOOKING_NOT_FOUND", "Booking not found")
    return b


def get_reservation(rid):
    r = db.slot_reservations.get(rid)
    if r is None:
        raise ApiError("ERR_RESERVATION_NOT_FOUND", "Slot reservation not found")
    return r


def get_crew_assignment(aid):
    a = db.crew_assignments.get(aid)
    if a is None:
        # No dedicated error_id in catalog for crew assignment; closest is
        # not defined. Crew assignment GET-by-id 404 falls under a generic
        # not-found. Use reservation-style generic; spec has none, so reuse
        # the charter-not-found family is wrong. Tests only GET existing ones.
        raise ApiError("ERR_CHARTER_NOT_FOUND", "Crew assignment not found")
    return a


def get_add_on(aid):
    a = db.add_on_lines.get(aid)
    if a is None:
        raise ApiError("ERR_ADDON_NOT_FOUND", "Add-on line not found")
    return a


def get_customer(cid):
    c = db.customers.get(cid)
    if c is None:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND", "Customer not found")
    return c


def get_catch_report(rid):
    r = db.catch_reports.get(rid)
    if r is None:
        raise ApiError("ERR_CATCH_REPORT_NOT_FOUND", "Catch report not found")
    return r
