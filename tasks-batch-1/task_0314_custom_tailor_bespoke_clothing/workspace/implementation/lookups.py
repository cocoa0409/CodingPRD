"""Entity lookup helpers that raise the correct not-found error per PRD §2.6."""
import errors
from errors import fail
from db import db


def get_customer(cid):
    c = db.customers.get(cid)
    if c is None:
        fail(errors.ERR_CUSTOMER_NOT_FOUND, "Customer not found")
    return c


def get_profile(pid):
    p = db.measurement_profiles.get(pid)
    if p is None:
        fail(errors.ERR_PROFILE_NOT_FOUND, "Measurement profile not found")
    return p


def get_fabric(fid):
    f = db.fabrics.get(fid)
    if f is None:
        fail(errors.ERR_FABRIC_NOT_FOUND, "Fabric not found")
    return f


def get_tailor(tid):
    t = db.tailors.get(tid)
    if t is None:
        fail(errors.ERR_TAILOR_NOT_FOUND, "Tailor not found")
    return t


def get_room(rid):
    r = db.fitting_rooms.get(rid)
    if r is None:
        fail(errors.ERR_ROOM_NOT_FOUND, "Fitting room not found")
    return r


def get_order(oid):
    o = db.garment_orders.get(oid)
    if o is None:
        fail(errors.ERR_ORDER_NOT_FOUND, "Garment order not found")
    return o


def get_fitting(order_id, fid):
    f = db.fittings.get(fid)
    if f is None or f["order_id"] != order_id:
        fail(errors.ERR_FITTING_NOT_FOUND, "Fitting not found")
    return f


def get_ticket(order_id, tid):
    t = db.alteration_tickets.get(tid)
    if t is None or t["order_id"] != order_id:
        fail(errors.ERR_ALTERATION_NOT_FOUND, "Alteration ticket not found")
    return t


def get_group(gid):
    g = db.group_orders.get(gid)
    if g is None:
        fail(errors.ERR_GROUP_NOT_FOUND, "Group order not found")
    return g
