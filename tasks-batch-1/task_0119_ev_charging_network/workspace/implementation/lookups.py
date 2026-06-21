"""Existence lookups (priority-3 ERR_NOT_FOUND, validated left-to-right)."""
import db
import errors


def _get(coll, _id):
    obj = coll.get(_id)
    if obj is None:
        raise errors.err(errors.ERR_NOT_FOUND, "resource not found: %s" % _id)
    return obj


def site(_id):
    return _get(db.sites, _id)


def stall(_id):
    return _get(db.stalls, _id)


def driver(_id):
    return _get(db.drivers, _id)


def emsp(_id):
    return _get(db.emsps, _id)


def tariff(_id):
    return _get(db.tariffs, _id)


def reservation(_id):
    return _get(db.reservations, _id)


def session(_id):
    return _get(db.sessions, _id)


def batch(_id):
    return _get(db.batches, _id)


def line_item(_id):
    return _get(db.line_items, _id)
