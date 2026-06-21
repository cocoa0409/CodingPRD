"""Existence lookups that raise the correct not-found error (404)."""
import db
import errors
from errors import ApiError


def get_service_area(sid):
    obj = db.service_areas.get(sid)
    if obj is None:
        raise ApiError(errors.ERR_SERVICE_AREA_NOT_FOUND, 404, "Service area not found.")
    return obj


def get_crew(cid):
    obj = db.crews.get(cid)
    if obj is None:
        raise ApiError(errors.ERR_CREW_NOT_FOUND, 404, "Crew not found.")
    return obj


def get_equipment(eid):
    obj = db.equipment.get(eid)
    if obj is None:
        raise ApiError(errors.ERR_EQUIPMENT_NOT_FOUND, 404, "Equipment not found.")
    return obj


def get_work_order(wid):
    obj = db.work_orders.get(wid)
    if obj is None:
        raise ApiError(errors.ERR_WORK_ORDER_NOT_FOUND, 404, "Work order not found.")
    return obj


def get_tree_on_wo(wid, tid):
    obj = db.trees.get(tid)
    if obj is None or obj["work_order_id"] != wid:
        raise ApiError(errors.ERR_TREE_NOT_FOUND, 404, "Tree not found.")
    return obj


def get_estimate_on_wo(wid, eid):
    obj = db.estimates.get(eid)
    if obj is None or obj["work_order_id"] != wid:
        raise ApiError(errors.ERR_ESTIMATE_NOT_FOUND, 404, "Estimate not found.")
    return obj


def get_permit_on_wo(wid, pid):
    obj = db.permits.get(pid)
    if obj is None or obj["work_order_id"] != wid:
        raise ApiError(errors.ERR_PERMIT_NOT_FOUND, 404, "Permit not found.")
    return obj


def get_disposal_ticket_on_wo(wid, tid):
    obj = db.disposal_tickets.get(tid)
    if obj is None or obj["work_order_id"] != wid:
        raise ApiError(errors.ERR_DISPOSAL_TICKET_NOT_FOUND, 404, "Disposal ticket not found.")
    return obj


def get_booking(bid):
    obj = db.bookings.get(bid)
    if obj is None:
        raise ApiError(errors.ERR_BOOKING_NOT_FOUND, 404, "Booking not found.")
    return obj


def get_estimate(eid):
    obj = db.estimates.get(eid)
    if obj is None:
        raise ApiError(errors.ERR_ESTIMATE_NOT_FOUND, 404, "Estimate not found.")
    return obj


def get_tree(tid):
    obj = db.trees.get(tid)
    if obj is None:
        raise ApiError(errors.ERR_TREE_NOT_FOUND, 404, "Tree not found.")
    return obj
