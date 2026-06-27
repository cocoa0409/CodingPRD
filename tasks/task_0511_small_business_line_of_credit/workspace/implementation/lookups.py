"""Existence lookups. Raise ERR_NOT_FOUND when a path/FK reference is missing."""
import db
from errors import err, ERR_NOT_FOUND


def _get(store, rid):
    if rid is None or rid not in store:
        raise err(ERR_NOT_FOUND, "Resource not found")
    return store[rid]


def get_merchant(rid):
    return _get(db.merchants, rid)


def get_bank_feed(rid):
    return _get(db.bank_feeds, rid)


def get_application(rid):
    return _get(db.applications, rid)


def get_credit_line(rid):
    return _get(db.credit_lines, rid)


def get_draw(rid):
    return _get(db.draws, rid)


def get_remittance(rid):
    return _get(db.remittances, rid)


def get_line_increase_request(rid):
    return _get(db.line_increase_requests, rid)


def get_renewal_offer(rid):
    return _get(db.renewal_offers, rid)


def get_statement(rid):
    return _get(db.statements, rid)


def get_ledger_entry(rid):
    return _get(db.ledger_entries, rid)
