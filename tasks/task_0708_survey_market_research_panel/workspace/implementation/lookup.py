"""Existence lookups (PRD §2.5: ERR_NOT_FOUND 404, validated left-to-right)."""
import db
import errors


def _get(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        errors.fail(errors.ERR_NOT_FOUND, "Resource %s not found" % _id)
    return rec


def study(_id):
    return _get(db.studies, _id)


def quota_cell(_id):
    return _get(db.quota_cells, _id)


def panelist(_id):
    return _get(db.panelists, _id)


def consent(_id):
    return _get(db.consents, _id)


def participation(_id):
    return _get(db.participations, _id)


def attention_check(_id):
    return _get(db.attention_checks, _id)


def accrual(_id):
    return _get(db.incentive_accruals, _id)


def payout_request(_id):
    return _get(db.payout_requests, _id)


def facility(_id):
    return _get(db.facilities, _id)


def focus_group(_id):
    return _get(db.focus_groups, _id)


def booking(_id):
    return _get(db.focus_group_bookings, _id)


def data_delivery(_id):
    return _get(db.data_deliveries, _id)
