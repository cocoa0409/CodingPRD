"""Request-shape, range and existence helpers.

The global precedence of PRD section 2.6 is honoured by the call order inside
each route handler:

  1 authentication            2 role authorisation      3 resource ownership
  4 segregation of duties     5 payer conflict          6 existence
  7 request shape             8 date-range sanity       9 quantity ranges
 10 cross-reference integrity 11 optimistic concurrency 12 state preconditions
 13 programme safety limits   14 temporal rules         15 constraint satisfaction
 16 fiscal capacity
"""

from decimal import Decimal, InvalidOperation

from flask import request

import db
from errors import ApiError


# ---------------------------------------------------------------------------
# body access
# ---------------------------------------------------------------------------

def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise ApiError("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return payload


def raw(payload, field):
    return payload.get(field)


def present(payload, field):
    return field in payload and payload.get(field) is not None


def fk(payload, field):
    """Return a mandatory body foreign key.

    A key that is absent or not a usable string is a shape problem rather than a
    resolution problem, so it is reported as ERR_INVALID_REQUEST; a key that is
    present and well formed is handed to the existence pass, which runs ahead of
    the rest of the shape checks.
    """
    value = payload.get(field)
    if not isinstance(value, str) or value.strip() == "":
        _bad(field, "is required and must be an identifier string")
    return value


def opt_fk(payload, field):
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or value.strip() == "":
        _bad(field, "must be an identifier string")
    return value


# ---------------------------------------------------------------------------
# shape (ERR_INVALID_REQUEST, 400)
# ---------------------------------------------------------------------------

def _bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def req_str(payload, field, min_len=1, max_len=None):
    if field not in payload or payload.get(field) is None:
        _bad(field, "is required")
    value = payload.get(field)
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if len(value) < min_len:
        _bad(field, "must have at least %d character(s)" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(field, "must have at most %d character(s)" % max_len)
    return value


def opt_str(payload, field, min_len=1, max_len=None, default=None):
    if field not in payload or payload.get(field) is None:
        return default
    return req_str(payload, field, min_len, max_len)


def req_enum(payload, field, allowed):
    value = req_str(payload, field)
    if value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(payload, field, allowed, default=None):
    if field not in payload or payload.get(field) is None:
        return default
    return req_enum(payload, field, allowed)


def _int_of(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    return value


def req_int(payload, field):
    if field not in payload or payload.get(field) is None:
        _bad(field, "is required")
    return _int_of(payload.get(field), field)


def opt_int(payload, field, default=None):
    if field not in payload or payload.get(field) is None:
        return default
    return _int_of(payload.get(field), field)


def _num_of(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(field, "must be a number")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        _bad(field, "must be a number")


def req_num(payload, field):
    if field not in payload or payload.get(field) is None:
        _bad(field, "is required")
    return _num_of(payload.get(field), field)


def opt_num(payload, field, default=None):
    if field not in payload or payload.get(field) is None:
        return default
    return _num_of(payload.get(field), field)


def req_date(payload, field):
    value = req_str(payload, field)
    parsed = db.parse_date(value)
    if parsed is None:
        _bad(field, "must be a YYYY-MM-DD calendar date")
    return parsed


def opt_date(payload, field, default=None):
    if field not in payload or payload.get(field) is None:
        return default
    return req_date(payload, field)


def req_bool(payload, field):
    if field not in payload or payload.get(field) is None:
        _bad(field, "is required")
    value = payload.get(field)
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


# ---------------------------------------------------------------------------
# quantity ranges (ERR_AMOUNT_OUT_OF_RANGE, 422)
# ---------------------------------------------------------------------------

def _range_error(field, why):
    raise ApiError("ERR_AMOUNT_OUT_OF_RANGE", "Field '%s' %s." % (field, why))


def int_min(field, value, minimum):
    if value < minimum:
        _range_error(field, "must be at least %d" % minimum)
    return value


def dec_between(field, value, low, high, places=4):
    if value < low or value > high:
        _range_error(field, "must lie between %s and %s" % (low, high))
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -places:
        _range_error(field, "may carry at most %d decimal places" % places)
    return value


def multiple_of(field, value, step, minimum):
    if value < minimum:
        _range_error(field, "must be at least %d" % minimum)
    if value % step != 0:
        _range_error(field, "must be a whole multiple of %d" % step)
    return value


def non_zero(field, value):
    if value == 0:
        _range_error(field, "must not be zero")
    return value


# ---------------------------------------------------------------------------
# date-range sanity (ERR_INVALID_DATE_RANGE, 422)
# ---------------------------------------------------------------------------

def range_inclusive(start, end):
    if end < start:
        raise ApiError("ERR_INVALID_DATE_RANGE", "The end date precedes the start date.")


def range_stay(checkin, checkout):
    if checkout <= checkin:
        raise ApiError("ERR_INVALID_DATE_RANGE",
                       "The departure date must be strictly after the arrival date.")


# ---------------------------------------------------------------------------
# existence (404)
# ---------------------------------------------------------------------------

def _lookup(table, identifier, error_id):
    if identifier is None:
        raise ApiError(error_id)
    record = table.get(identifier)
    if record is None:
        raise ApiError(error_id)
    return record


def get_hotel(identifier):
    return _lookup(db.store.hotels, identifier, "ERR_HOTEL_NOT_FOUND")


def get_rate_plan(identifier):
    return _lookup(db.store.rate_plans, identifier, "ERR_RATE_PLAN_NOT_FOUND")


def get_member(identifier):
    return _lookup(db.store.members, identifier, "ERR_MEMBER_NOT_FOUND")


def get_stay(identifier):
    return _lookup(db.store.stays, identifier, "ERR_STAY_NOT_FOUND")


def get_redemption(identifier):
    return _lookup(db.store.redemptions, identifier, "ERR_REDEMPTION_NOT_FOUND")


def get_delivery(identifier):
    return _lookup(db.store.deliveries, identifier, "ERR_DELIVERY_NOT_FOUND")


def get_batch(identifier):
    return _lookup(db.store.batches, identifier, "ERR_BATCH_NOT_FOUND")


def get_window(identifier):
    return _lookup(db.store.blackout_windows, identifier, "ERR_BLACKOUT_WINDOW_NOT_FOUND")


def get_partner(identifier):
    return _lookup(db.store.partners, identifier, "ERR_PARTNER_NOT_FOUND")


def get_purchase(identifier):
    return _lookup(db.store.purchases, identifier, "ERR_PURCHASE_NOT_FOUND")


def get_complaint(identifier):
    return _lookup(db.store.complaints, identifier, "ERR_COMPLAINT_NOT_FOUND")


def get_pricing(identifier):
    return _lookup(db.store.pricing_rows, identifier, "ERR_PRICING_ROW_NOT_FOUND")


def get_entry(identifier):
    record = db.store.ledger_entries.get(identifier)
    if record is None:
        raise ApiError("ERR_NOT_FOUND", "No such point ledger entry.")
    return record
