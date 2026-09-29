"""Lookup, filter and pagination helpers shared by the route modules."""

import errors
from errors import fail
from store import db, ordered
from validators import pagination, query_enum, query_value


def _get(collection, identifier, spec):
    if not isinstance(identifier, str):
        fail(spec, "identifier must be a string")
    record = collection.get(identifier)
    if record is None:
        fail(spec, "%s does not exist" % identifier)
    return record


def get_channel(identifier):
    return _get(db.channels, identifier, errors.ERR_CHANNEL_NOT_FOUND)


def get_gallery(identifier):
    return _get(db.galleries, identifier, errors.ERR_GALLERY_NOT_FOUND)


def get_rep(identifier):
    return _get(db.reps, identifier, errors.ERR_REPRESENTATIVE_NOT_FOUND)


def get_prospect(identifier):
    return _get(db.prospects, identifier, errors.ERR_PROSPECT_NOT_FOUND)


def get_booking(identifier):
    return _get(db.bookings, identifier, errors.ERR_BOOKING_NOT_FOUND)


def get_presentation(identifier):
    return _get(db.presentations, identifier, errors.ERR_PRESENTATION_NOT_FOUND)


def get_agreement(identifier):
    return _get(db.agreements, identifier, errors.ERR_AGREEMENT_NOT_FOUND)


def get_financing(identifier):
    return _get(db.financings, identifier, errors.ERR_FINANCING_APPLICATION_NOT_FOUND)


def get_rescission(identifier):
    return _get(db.rescissions, identifier, errors.ERR_RESCISSION_REQUEST_NOT_FOUND)


def get_refund(identifier):
    return _get(db.refunds, identifier, errors.ERR_REFUND_DISBURSEMENT_NOT_FOUND)


def get_package(identifier):
    return _get(db.packages, identifier, errors.ERR_CLOSING_PACKAGE_NOT_FOUND)


def get_retraining(identifier):
    return _get(db.retrainings, identifier, errors.ERR_RETRAINING_ASSIGNMENT_NOT_FOUND)


# ------------------------------------------------------------------- lists
def collect(collection, filters):
    """Return the matching rows in created_at ASC order.

    `filters` is a sequence of (field_name, query_param_name) pairs, optionally
    with a third element listing the legal enum members for that parameter.  A
    query parameter that was not supplied does not filter.
    """
    rows = ordered(collection.values())
    for entry in filters:
        field = entry[0]
        param = entry[1]
        allowed = entry[2] if len(entry) > 2 else None
        if allowed is not None:
            value = query_enum(param, allowed)
        else:
            value = query_value(param)
        if value is None:
            continue
        rows = [row for row in rows if _matches(row.get(field), value)]
    return rows


def _matches(actual, wanted):
    if actual is None:
        return False
    return str(actual) == wanted


def page():
    return pagination()
