"""Entity lookup helpers that raise ERR_NOT_FOUND when absent (PRD §2.8)."""
from db import db
from errors import err, ERR_NOT_FOUND


def get_venue(vid):
    v = db.venues.get(vid)
    if v is None:
        raise err(ERR_NOT_FOUND, "Venue not found")
    return v


def get_membership(mid):
    m = db.memberships.get(mid)
    if m is None:
        raise err(ERR_NOT_FOUND, "Membership not found")
    return m


def get_show(sid):
    s = db.shows.get(sid)
    if s is None:
        raise err(ERR_NOT_FOUND, "Show not found")
    return s


def get_show_booking(bid):
    b = db.show_bookings.get(bid)
    if b is None:
        raise err(ERR_NOT_FOUND, "Show booking not found")
    return b


def get_group_booking(gid):
    g = db.group_bookings.get(gid)
    if g is None:
        raise err(ERR_NOT_FOUND, "Group booking not found")
    return g


def get_program(pid):
    p = db.programs.get(pid)
    if p is None:
        raise err(ERR_NOT_FOUND, "Program session not found")
    return p


def get_registration(rid):
    r = db.registrations.get(rid)
    if r is None:
        raise err(ERR_NOT_FOUND, "Registration not found")
    return r


def get_rental(rid):
    r = db.rentals.get(rid)
    if r is None:
        raise err(ERR_NOT_FOUND, "Rental not found")
    return r


def get_sponsor(sid):
    s = db.sponsors.get(sid)
    if s is None:
        raise err(ERR_NOT_FOUND, "Sponsor not found")
    return s


def get_accommodation(aid):
    a = db.accommodations.get(aid)
    if a is None:
        raise err(ERR_NOT_FOUND, "Accommodation request not found")
    return a
