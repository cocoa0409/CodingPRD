"""Entity -> public JSON serializers. Internal fields prefixed with '_' are
stripped; computed aggregates are filled in on read."""
from db import db
from services.aggregates import (
    recompute_seats_booked,
    recompute_catch_total,
    recompute_open_slot_count,
)


def _public(entity):
    """Strip internal helper fields (those starting with '_')."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def marina_out(m):
    out = _public(m)
    out["open_slot_count"] = recompute_open_slot_count(m)
    return out


def dock_slot_out(s):
    return _public(s)


def boat_out(b):
    return _public(b)


def captain_out(c):
    return _public(c)


def mate_out(m):
    return _public(m)


def permit_out(p):
    return _public(p)


def customer_out(c):
    return _public(c)


def charter_out(ch):
    out = _public(ch)
    out["seats_booked"] = recompute_seats_booked(ch)
    out["catch_total"] = recompute_catch_total(ch)
    return out


def slot_reservation_out(r):
    return _public(r)


def crew_assignment_out(a):
    return _public(a)


def booking_out(b):
    return _public(b)


def add_on_line_out(a):
    return _public(a)


def catch_report_out(r):
    return _public(r)
