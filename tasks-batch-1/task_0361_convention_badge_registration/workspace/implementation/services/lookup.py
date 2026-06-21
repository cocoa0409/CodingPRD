"""Existence resolution and ownership checks (PRD §2.1, §2.8)."""
import db
import errors


def _get(collection, rid):
    if rid not in collection:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found")
    return collection[rid]


def convention(rid):
    return _get(db.conventions, rid)


def ticket_type(rid):
    return _get(db.ticket_types, rid)


def attendee(rid):
    return _get(db.attendees, rid)


def order(rid):
    return _get(db.orders, rid)


def ticket_line_item(rid):
    return _get(db.ticket_line_items, rid)


def badge(rid):
    return _get(db.badges, rid)


def session(rid):
    return _get(db.sessions, rid)


def session_reservation(rid):
    return _get(db.session_reservations, rid)


def waitlist_entry(rid):
    return _get(db.waitlist_entries, rid)


def exhibitor(rid):
    return _get(db.exhibitors, rid)


def booth(rid):
    return _get(db.booths, rid)


def booth_booking(rid):
    return _get(db.booth_bookings, rid)


# --------------------------------------------------------------------------- #
# Ownership checks (PRD §2.1) — entity-backed roles act only on resources they own.
# Opaque roles (ConventionAdmin, RegistrationAgent, Anonymous) are not restricted.
# --------------------------------------------------------------------------- #
def require_attendee_owns(role, user_id, attendee_id):
    """When acting as Attendee, the resource's attendee FK must equal X-User-ID."""
    if role == "Attendee" and attendee_id != user_id:
        raise errors.err(errors.ERR_FORBIDDEN, "Attendee does not own this resource")


def require_exhibitor_owns(role, user_id, exhibitor_id):
    """When acting as Exhibitor, the booking's exhibitor_id must equal X-User-ID."""
    if role == "Exhibitor" and exhibitor_id != user_id:
        raise errors.err(errors.ERR_FORBIDDEN, "Exhibitor does not own this resource")
