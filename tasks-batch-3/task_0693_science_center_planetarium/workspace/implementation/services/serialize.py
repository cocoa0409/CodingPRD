"""Serialization: produce the public JSON view of each entity.

Internal-only fields (those prefixed with `_`) are stripped. The remaining
fields are exactly those declared in SCAFFOLD §1.1 plus the common fields.
"""


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def venue_view(v):
    return _public(v)


def membership_view(m):
    return _public(m)


def show_view(s):
    return _public(s)


def show_booking_view(b):
    return _public(b)


def group_booking_view(g):
    return _public(g)


def program_view(p):
    return _public(p)


def registration_view(r):
    return _public(r)


def rental_view(r):
    return _public(r)


def sponsor_view(s):
    return _public(s)


def contribution_view(c):
    return _public(c)


def accommodation_view(a):
    return _public(a)
