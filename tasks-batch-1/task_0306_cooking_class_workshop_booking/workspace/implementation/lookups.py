"""Existence lookups (priority 4 -> ERR_NOT_FOUND) and ownership checks."""
import db
from errors import err


def get_or_404(store, rid):
    obj = store.get(rid)
    if obj is None:
        raise err("ERR_NOT_FOUND", "Resource not found: %s" % rid)
    return obj


def get_instructor(rid):
    return get_or_404(db.instructors, rid)


def get_member(rid):
    return get_or_404(db.members, rid)


def get_template(rid):
    return get_or_404(db.templates, rid)


def get_series(rid):
    return get_or_404(db.series, rid)


def get_session(rid):
    return get_or_404(db.sessions, rid)


def get_ingredient_line(rid):
    return get_or_404(db.ingredient_lines, rid)


def get_booking(rid):
    return get_or_404(db.bookings, rid)


def get_waitlist_entry(rid):
    return get_or_404(db.waitlist_entries, rid)


def get_substitution(rid):
    return get_or_404(db.substitutions, rid)


def get_gift_card(rid):
    return get_or_404(db.gift_cards, rid)


def get_gift_card_txn(rid):
    return get_or_404(db.gift_card_txns, rid)


def get_no_show_record(rid):
    return get_or_404(db.no_show_records, rid)


# --------------------------------------------------------------------------
# Ownership (priority 3 -> ERR_NOT_RESOURCE_OWNER). StudioAdmin bypasses.
# --------------------------------------------------------------------------
def require_session_owner(principal, session):
    if principal.role == "Instructor" and session["instructor_id"] != principal.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Instructor does not teach this session")


def require_booking_owner(principal, booking):
    if principal.role == "Member" and booking["member_id"] != principal.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Member does not own this booking")


def require_waitlist_owner(principal, entry):
    if principal.role == "Member" and entry["member_id"] != principal.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Member does not own this waitlist entry")


def require_gift_card_owner(principal, gift_card):
    if principal.role == "Member" and gift_card["owner_member_id"] != principal.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Member does not own this gift card")
