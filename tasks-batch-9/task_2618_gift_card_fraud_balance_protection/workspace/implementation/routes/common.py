"""Shared route helpers: existence lookups in ladder order and list plumbing."""
import db as dbm
import response
import validate
from db import db
from errors import fail
from middleware import ALL_ROLES, authenticate, scope_record, scope_store  # noqa: F401

READ_ROLES = ALL_ROLES


def require_store(store_id):
    rec = db.stores.get(store_id) if isinstance(store_id, str) else None
    if rec is None:
        fail("ERR_STORE_NOT_FOUND")
    return rec


def require_rack(rack_id):
    rec = db.racks.get(rack_id) if isinstance(rack_id, str) else None
    if rec is None:
        fail("ERR_RACK_NOT_FOUND")
    return rec


def require_card(card_id):
    rec = db.cards.get(card_id) if isinstance(card_id, str) else None
    if rec is None:
        fail("ERR_CARD_NOT_FOUND")
    return rec


def require_issuance(issuance_id):
    rec = db.issuances.get(issuance_id) if isinstance(issuance_id, str) else None
    if rec is None:
        fail("ERR_ISSUANCE_REQUEST_NOT_FOUND")
    return rec


def require_bulk_order(order_id):
    rec = db.bulk_orders.get(order_id) if isinstance(order_id, str) else None
    if rec is None:
        fail("ERR_BULK_ORDER_NOT_FOUND")
    return rec


def require_alert(alert_id):
    rec = db.alerts.get(alert_id) if isinstance(alert_id, str) else None
    if rec is None:
        fail("ERR_ALERT_NOT_FOUND")
    return rec


def require_claim(claim_id):
    rec = db.claims.get(claim_id) if isinstance(claim_id, str) else None
    if rec is None:
        fail("ERR_CLAIM_NOT_FOUND")
    return rec


def require_listing(listing_id):
    rec = db.listings.get(listing_id) if isinstance(listing_id, str) else None
    if rec is None:
        fail("ERR_LISTING_NOT_FOUND")
    return rec


def require_period(period_id):
    rec = db.periods.get(period_id) if isinstance(period_id, str) else None
    if rec is None:
        fail("ERR_PERIOD_NOT_FOUND")
    return rec


def require_event(event_id):
    rec = db.events.get(event_id) if isinstance(event_id, str) else None
    if rec is None:
        fail("ERR_LEDGER_EVENT_NOT_FOUND")
    return rec


def require_hold(hold_id):
    rec = db.holds.get(hold_id) if isinstance(hold_id, str) else None
    if rec is None:
        fail("ERR_HOLD_NOT_FOUND")
    return rec


def require_referral(referral_id):
    rec = db.referrals.get(referral_id) if isinstance(referral_id, str) else None
    if rec is None:
        fail("ERR_ALERT_NOT_FOUND")
    return rec


def listing_response(rows, order_keys=None):
    """Paginate a list, ordered by the endpoint's declared keys and always
    tie-broken by created_at ASC (never by id)."""
    limit, offset = validate.pagination()
    if order_keys:
        rows = dbm.sorted_rows(rows, order_keys)
    else:
        rows = dbm.by_created(rows)
    page, total = validate.paginate(rows, limit, offset)
    return response.collection(page, limit, offset, total)


def filter_by(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]
