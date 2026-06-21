"""Resource lookup helpers that raise the correct not-found error (PRD §2.7)."""
import db
import errors
from errors import err

_NOT_FOUND = {
    "venue": errors.ERR_VENUE_NOT_FOUND,
    "section": errors.ERR_SECTION_NOT_FOUND,
    "event": errors.ERR_EVENT_NOT_FOUND,
    "seller": errors.ERR_SELLER_NOT_FOUND,
    "buyer": errors.ERR_BUYER_NOT_FOUND,
    "listing": errors.ERR_LISTING_NOT_FOUND,
    "seat": errors.ERR_SEAT_NOT_FOUND,
    "order": errors.ERR_ORDER_NOT_FOUND,
    "transfer": errors.ERR_TRANSFER_NOT_FOUND,
    "payout": errors.ERR_PAYOUT_NOT_FOUND,
    "guarantee_claim": errors.ERR_CLAIM_NOT_FOUND,
    "event_credit": errors.ERR_CREDIT_NOT_FOUND,
    "fraud_flag": errors.ERR_FLAG_NOT_FOUND,
}


def get(kind, rid):
    table = db.TABLES[kind]
    rec = table.get(rid)
    if rec is None:
        raise err(_NOT_FOUND[kind], "%s not found" % kind)
    return rec


def get_venue(rid):
    return get("venue", rid)


def get_section(rid):
    return get("section", rid)


def get_event(rid):
    return get("event", rid)


def get_seller(rid):
    return get("seller", rid)


def get_buyer(rid):
    return get("buyer", rid)


def get_listing(rid):
    return get("listing", rid)


def get_seat(rid):
    return get("seat", rid)


def get_order(rid):
    return get("order", rid)


def get_transfer(rid):
    return get("transfer", rid)


def get_payout(rid):
    return get("payout", rid)


def get_claim(rid):
    return get("guarantee_claim", rid)


def get_credit(rid):
    return get("event_credit", rid)


def get_flag(rid):
    return get("fraud_flag", rid)
