"""Existence lookups (PRD §2.8 step 4) and ownership checks (step 5)."""
import db
from errors import ApiError


def _get(collection, entity_id, error_id):
    if not isinstance(entity_id, str):
        raise ApiError(error_id)
    record = collection.get(entity_id)
    if record is None:
        raise ApiError(error_id)
    return record


def organizer(entity_id):
    return _get(db.store.organizers, entity_id, "ERR_ORGANIZER_NOT_FOUND")


def venue(entity_id):
    return _get(db.store.venues, entity_id, "ERR_VENUE_NOT_FOUND")


def buyer(entity_id):
    return _get(db.store.buyers, entity_id, "ERR_BUYER_NOT_FOUND")


def event(entity_id):
    return _get(db.store.events, entity_id, "ERR_EVENT_NOT_FOUND")


def ticket_type(entity_id):
    return _get(db.store.ticket_types, entity_id, "ERR_TICKET_TYPE_NOT_FOUND")


def seat_block(entity_id):
    return _get(db.store.seat_blocks, entity_id, "ERR_SEAT_BLOCK_NOT_FOUND")


def promo_code(entity_id):
    return _get(db.store.promo_codes, entity_id, "ERR_PROMO_CODE_NOT_FOUND")


def order(entity_id):
    return _get(db.store.orders, entity_id, "ERR_ORDER_NOT_FOUND")


def order_item(entity_id):
    return _get(db.store.order_items, entity_id, "ERR_ORDER_ITEM_NOT_FOUND")


def attendee(entity_id):
    return _get(db.store.attendees, entity_id, "ERR_ATTENDEE_NOT_FOUND")


def scan(entity_id):
    return _get(db.store.scans, entity_id, "ERR_SCAN_NOT_FOUND")


def refund_request(entity_id):
    return _get(db.store.refund_requests, entity_id, "ERR_REFUND_REQUEST_NOT_FOUND")


def transfer_request(entity_id):
    return _get(db.store.transfer_requests, entity_id, "ERR_TRANSFER_REQUEST_NOT_FOUND")


def waitlist_entry(entity_id):
    return _get(db.store.waitlist_entries, entity_id, "ERR_WAITLIST_ENTRY_NOT_FOUND")


def payout(entity_id):
    return _get(db.store.payouts, entity_id, "ERR_PAYOUT_NOT_FOUND")


# --------------------------------------------------------------------------
# ownership
# --------------------------------------------------------------------------
def unauthorized():
    raise ApiError("ERR_UNAUTHORIZED", "The acting principal does not own this resource.")


def require_organizer_owns_event(actor, event_record):
    if actor.role == "Organizer" and actor.user_id != event_record["organizer_id"]:
        unauthorized()


def require_buyer_is(actor, buyer_id):
    if actor.role == "Buyer" and actor.user_id != buyer_id:
        unauthorized()


def event_of_ticket_type(ticket_type_record):
    return db.store.events.get(ticket_type_record["event_id"])


def event_of_order(order_record):
    return db.store.events.get(order_record["event_id"])
