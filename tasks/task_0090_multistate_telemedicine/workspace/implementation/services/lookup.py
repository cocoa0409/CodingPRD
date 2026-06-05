"""Existence resolution (priority-3 ERR_NOT_FOUND, 404).

Path ids are validated left-to-right (PRD §2.5): the first unresolved id in the
path fails; body FKs are validated after path ids.
"""
import db
from errors import err, ERR_NOT_FOUND


def _get(store, _id):
    rec = store.get(_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Resource not found: %s" % _id)
    return rec


def physician(_id):
    return _get(db.physicians, _id)


def state_license(_id):
    return _get(db.state_licenses, _id)


def patient(_id):
    return _get(db.patients, _id)


def payer(_id):
    return _get(db.payers, _id)


def visit(_id):
    return _get(db.visits, _id)


def prescription(_id):
    return _get(db.prescriptions, _id)


def claim(_id):
    return _get(db.claims, _id)


def follow_up(_id):
    return _get(db.follow_ups, _id)
