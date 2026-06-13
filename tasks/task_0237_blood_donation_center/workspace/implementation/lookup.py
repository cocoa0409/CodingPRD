"""Existence lookups that raise the resource-specific 404 on miss."""
import db
import errors
from errors import ApiError


def _get(collection, rid, error_id):
    rec = collection.get(rid)
    if rec is None:
        raise ApiError(error_id, 404, "Resource not found: %s" % rid)
    return rec


def center(rid):
    return _get(db.centers, rid, errors.ERR_CENTER_NOT_FOUND)


def donor(rid):
    return _get(db.donors, rid, errors.ERR_DONOR_NOT_FOUND)


def deferral(rid):
    return _get(db.deferrals, rid, errors.ERR_DEFERRAL_NOT_FOUND)


def slot(rid):
    return _get(db.slots, rid, errors.ERR_SLOT_NOT_FOUND)


def appointment(rid):
    return _get(db.appointments, rid, errors.ERR_APPOINTMENT_NOT_FOUND)


def screening(rid):
    return _get(db.screenings, rid, errors.ERR_SCREENING_NOT_FOUND)


def donation(rid):
    return _get(db.donations, rid, errors.ERR_DONATION_NOT_FOUND)


def test_result(rid):
    return _get(db.test_results, rid, errors.ERR_TEST_RESULT_NOT_FOUND)


def blood_unit(rid):
    return _get(db.blood_units, rid, errors.ERR_UNIT_NOT_FOUND)


def reaction(rid):
    return _get(db.adverse_reactions, rid, errors.ERR_REACTION_NOT_FOUND)


def recall_event(rid):
    return _get(db.recall_events, rid, errors.ERR_RECALL_EVENT_NOT_FOUND)


def bucket(rid):
    return _get(db.inventory_buckets, rid, errors.ERR_BUCKET_NOT_FOUND)
