"""Existence lookups (ERR_NOT_FOUND) and list pagination helpers (PRD §2.3, §2.10)."""
import db
import errors
import serialize
from validate_input import opt_int_param


def get_or_404(store, rid):
    rec = store.get(rid)
    if rec is None:
        errors.err(errors.ERR_NOT_FOUND, "Referenced resource does not exist")
    return rec


def get_park(rid):
    return get_or_404(db.parks, rid)


def get_ride(rid):
    return get_or_404(db.rides, rid)


def get_window(rid):
    return get_or_404(db.return_windows, rid)


def get_guest(rid):
    return get_or_404(db.guests, rid)


def get_party(rid):
    return get_or_404(db.parties, rid)


def get_membership(rid):
    return get_or_404(db.party_memberships, rid)


def get_plan(rid):
    return get_or_404(db.entitlement_plans, rid)


def get_ticket(rid):
    return get_or_404(db.guest_day_tickets, rid)


def get_reservation(rid):
    return get_or_404(db.reservations, rid)


def get_purchase(rid):
    return get_or_404(db.lightning_lane_purchases, rid)


def paginate_and_respond(kind, records, response):
    """Sort by created_at asc (stable via _seq), paginate, and build array envelope."""
    limit = opt_int_param("limit", 10, min_val=1, max_val=100)
    offset = opt_int_param("offset", 0, min_val=0)
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    items = [serialize.view(kind, r) for r in page]
    return response.array_response(items, limit, offset, total)
