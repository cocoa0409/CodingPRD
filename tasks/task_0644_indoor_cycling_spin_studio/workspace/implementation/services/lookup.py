"""Existence + scope-match resolution (PRD §2.5, validation priority 3).

Path identifiers are validated strictly left to right; the first identifier that
does not resolve (or is out of scope) yields ERR_NOT_FOUND.
"""
from db import db
from errors import err, ERR_NOT_FOUND


def get_studio(studio_id):
    s = db.studios.get(studio_id)
    if s is None:
        raise err(ERR_NOT_FOUND, "Studio not found")
    return s


def get_room(room_id):
    r = db.rooms.get(room_id)
    if r is None:
        raise err(ERR_NOT_FOUND, "Room not found")
    return r


def get_room_in_studio(studio_id, room_id):
    get_studio(studio_id)
    r = get_room(room_id)
    if r["studio_id"] != studio_id:
        raise err(ERR_NOT_FOUND, "Room not found in studio")
    return r


def get_bike(bike_id):
    b = db.bikes.get(bike_id)
    if b is None:
        raise err(ERR_NOT_FOUND, "Bike not found")
    return b


def get_bike_in_room(studio_id, room_id, bike_id):
    get_room_in_studio(studio_id, room_id)
    b = get_bike(bike_id)
    if b["room_id"] != room_id:
        raise err(ERR_NOT_FOUND, "Bike not found in room")
    return b


def get_instructor(instructor_id):
    i = db.instructors.get(instructor_id)
    if i is None:
        raise err(ERR_NOT_FOUND, "Instructor not found")
    return i


def get_session(session_id):
    s = db.sessions.get(session_id)
    if s is None:
        raise err(ERR_NOT_FOUND, "Session not found")
    return s


def get_session_in_studio(studio_id, session_id):
    get_studio(studio_id)
    s = get_session(session_id)
    if s["studio_id"] != studio_id:
        raise err(ERR_NOT_FOUND, "Session not found in studio")
    return s


def get_member(member_id):
    m = db.members.get(member_id)
    if m is None:
        raise err(ERR_NOT_FOUND, "Member not found")
    return m


def get_pack(pack_id):
    p = db.credit_packs.get(pack_id)
    if p is None:
        raise err(ERR_NOT_FOUND, "Credit pack not found")
    return p


def get_reservation(reservation_id):
    r = db.reservations.get(reservation_id)
    if r is None:
        raise err(ERR_NOT_FOUND, "Reservation not found")
    return r


def get_reservation_in_session(studio_id, session_id, reservation_id):
    get_session_in_studio(studio_id, session_id)
    r = get_reservation(reservation_id)
    if r["session_id"] != session_id:
        raise err(ERR_NOT_FOUND, "Reservation not found in session")
    return r


def get_waitlist_entry(entry_id):
    w = db.waitlist_entries.get(entry_id)
    if w is None:
        raise err(ERR_NOT_FOUND, "Waitlist entry not found")
    return w


def get_waitlist_in_session(studio_id, session_id, entry_id):
    get_session_in_studio(studio_id, session_id)
    w = get_waitlist_entry(entry_id)
    if w["session_id"] != session_id:
        raise err(ERR_NOT_FOUND, "Waitlist entry not found in session")
    return w


def get_product(product_id):
    p = db.products.get(product_id)
    if p is None:
        raise err(ERR_NOT_FOUND, "Product not found")
    return p


def get_product_in_studio(studio_id, product_id):
    get_studio(studio_id)
    p = get_product(product_id)
    if p["studio_id"] != studio_id:
        raise err(ERR_NOT_FOUND, "Product not found in studio")
    return p


def get_retail_order(order_id):
    o = db.retail_orders.get(order_id)
    if o is None:
        raise err(ERR_NOT_FOUND, "Retail order not found")
    return o


def get_penalty(charge_id):
    p = db.penalty_charges.get(charge_id)
    if p is None:
        raise err(ERR_NOT_FOUND, "Penalty charge not found")
    return p
