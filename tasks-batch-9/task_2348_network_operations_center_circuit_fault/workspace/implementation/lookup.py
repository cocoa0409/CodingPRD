"""Existence resolution helpers (bands 4 and 5)."""

import db
from errors import fail


def _get(collection, ident, error_id, required=True):
    if not isinstance(ident, str) or ident == "":
        if required:
            fail(error_id)
        return None
    rec = collection.get(ident)
    if rec is None and required:
        fail(error_id)
    return rec


def carrier(ident, required=True):
    return _get(db.db.carriers, ident, "ERR_CARRIER_NOT_FOUND", required)


def circuit(ident, required=True):
    return _get(db.db.circuits, ident, "ERR_CIRCUIT_NOT_FOUND", required)


def device(ident, required=True):
    return _get(db.db.devices, ident, "ERR_DEVICE_NOT_FOUND", required)


def path(ident, required=True):
    return _get(db.db.paths, ident, "ERR_PATH_NOT_FOUND", required)


def segment(ident, required=True):
    return _get(db.db.segments, ident, "ERR_SEGMENT_NOT_FOUND", required)


def alarm(ident, required=True):
    return _get(db.db.alarms, ident, "ERR_ALARM_NOT_FOUND", required)


def incident(ident, required=True):
    return _get(db.db.incidents, ident, "ERR_INCIDENT_NOT_FOUND", required)


def ticket(ident, required=True):
    return _get(db.db.tickets, ident, "ERR_TICKET_NOT_FOUND", required)


def claim(ident, required=True):
    return _get(db.db.claims, ident, "ERR_CLAIM_NOT_FOUND", required)


def window(ident, required=True):
    return _get(db.db.windows, ident, "ERR_WINDOW_NOT_FOUND", required)


def failover_test(ident, required=True):
    return _get(db.db.failover_tests, ident, "ERR_TEST_NOT_FOUND", required)


def order(ident, required=True):
    return _get(db.db.orders, ident, "ERR_ORDER_NOT_FOUND", required)


def review(ident, required=True):
    return _get(db.db.reviews, ident, "ERR_REVIEW_NOT_FOUND", required)
