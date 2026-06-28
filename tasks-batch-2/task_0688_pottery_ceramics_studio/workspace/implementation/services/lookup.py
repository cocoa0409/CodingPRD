"""Entity lookup + ownership helpers (PRD §2.1, §2.8, §2.10).

Existence (ERR_NOT_FOUND) is checked left-to-right before state/business rules.
LoyaltyMember ownership (ERR_NOT_RESOURCE_OWNER) compares the resource's owning
member_id to the caller's X-User-ID.
"""

from db import db
from errors import not_found, not_resource_owner


def get_member(member_id):
    m = db.loyalty_members.get(member_id)
    if m is None:
        raise not_found("LoyaltyMember %s not found" % member_id)
    return m


def get_item(item_id):
    r = db.paint_bar_items.get(item_id)
    if r is None:
        raise not_found("PaintBarItem %s not found" % item_id)
    return r


def get_visit(visit_id):
    r = db.studio_visits.get(visit_id)
    if r is None:
        raise not_found("StudioVisit %s not found" % visit_id)
    return r


def get_piece(piece_id):
    r = db.bisque_pieces.get(piece_id)
    if r is None:
        raise not_found("BisquePiece %s not found" % piece_id)
    return r


def get_batch(batch_id):
    r = db.kiln_batches.get(batch_id)
    if r is None:
        raise not_found("KilnBatch %s not found" % batch_id)
    return r


def get_booking(booking_id):
    r = db.party_bookings.get(booking_id)
    if r is None:
        raise not_found("PartyBooking %s not found" % booking_id)
    return r


def get_series(series_id):
    r = db.class_series.get(series_id)
    if r is None:
        raise not_found("ClassSeries %s not found" % series_id)
    return r


def get_enrollment(enrollment_id):
    r = db.enrollments.get(enrollment_id)
    if r is None:
        raise not_found("Enrollment %s not found" % enrollment_id)
    return r


def assert_member_owns(caller, owning_member_id):
    """If the caller is a LoyaltyMember, the resource's owning member_id must
    equal X-User-ID. Opaque roles are never ownership-checked."""
    if caller.is_member and owning_member_id != caller.user_id:
        raise not_resource_owner()
