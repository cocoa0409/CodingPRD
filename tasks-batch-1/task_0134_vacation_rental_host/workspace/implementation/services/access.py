"""Entity lookup, FK resolution, and ownership checks.

Validation priority (PRD §2.9):
  3 existence (path) -> ERR_NOT_FOUND
  4 body FK existence -> ERR_FK_NOT_FOUND
  5 ownership        -> ERR_NOT_RESOURCE_OWNER
"""
from db import db
from errors import err


def get_or_404(coll, _id):
    """Resolve a path-referenced id; ERR_NOT_FOUND (404) if absent."""
    ent = coll.get(_id)
    if ent is None:
        raise err("ERR_NOT_FOUND", "resource not found")
    return ent


def fk_or_404(coll, _id):
    """Resolve a body foreign key; ERR_FK_NOT_FOUND (404) if absent."""
    ent = coll.get(_id)
    if ent is None:
        raise err("ERR_FK_NOT_FOUND", "referenced resource not found")
    return ent


# ---- Ownership (PRD §2.1) -------------------------------------------------

def listing_owner_host_id(listing):
    return listing["host_id"]


def require_host_owns_listing(listing, user_id, role):
    """A Host caller must own the listing (listing.host_id == X-User-ID)."""
    if role == "Host" and listing["host_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "host does not own this listing")


def require_guest_owns_booking(booking, user_id, role):
    """A Guest caller must be booking.guest_id (PRD §2.1)."""
    if role == "Guest" and booking["guest_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "guest does not own this booking")


def listing_of_booking(booking):
    return db.listings.get(booking["listing_id"])


def booking_of_deposit(deposit):
    return db.bookings.get(deposit["booking_id"])


def deposit_of_claim(claim):
    return db.security_deposits.get(claim["security_deposit_id"])


def booking_of_claim(claim):
    dep = deposit_of_claim(claim)
    return booking_of_deposit(dep) if dep else None


def listing_of_channel(conn):
    return db.listings.get(conn["listing_id"])


def require_host_owns_via_listing(listing, user_id, role):
    require_host_owns_listing(listing, user_id, role)
