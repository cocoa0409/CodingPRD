"""Rungs 1-8 of the global validation ladder (PRD 2.10).

Rung 1/2  X-User-ID and X-User-Role -> ERR_UNAUTHENTICATED
Rung 3    role authorised for the operation -> ERR_UNAUTHORIZED
Rung 5/6  path and body reference existence -> per-kind not-found code
Rung 7    body shape / enums / ranges / dates / fractions -> ERR_INVALID_REQUEST
Rung 8    pagination bounds -> ERR_INVALID_REQUEST
"""

import datetime
import re
from decimal import Decimal, InvalidOperation

from flask import request

from db import db
from errors import ApiError

ROLES = (
    "TitleAnalyst",
    "AcquisitionManager",
    "DivisionOrderAdmin",
    "Operator",
    "RoyaltyOwner",
    "PlatformAdmin",
)

STATE_CODES = ("TX", "OK", "NM", "ND")


# --------------------------------------------------------------------------
# rungs 1-3
# --------------------------------------------------------------------------
def authorize(*allowed_roles):
    user_id = request.headers.get("X-User-ID")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or not a declared role.")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % role)
    return user_id, role


# --------------------------------------------------------------------------
# rung 7 helpers: body access and shape checks
# --------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def _present(payload, field):
    return field in payload and payload[field] is not None


def req_str(payload, field, min_len=1, max_len=None):
    if not _present(payload, field):
        _bad(field, "is required")
    value = payload[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if len(value) < min_len:
        _bad(field, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(field, "must be at most %d characters" % max_len)
    return value


def opt_str(payload, field, default=None, min_len=1, max_len=None):
    if not _present(payload, field):
        return default
    return req_str(payload, field, min_len=min_len, max_len=max_len)


def req_enum(payload, field, choices):
    value = req_str(payload, field)
    if value not in choices:
        _bad(field, "must be one of %s" % ", ".join(choices))
    return value


def opt_enum(payload, field, choices, default=None):
    if not _present(payload, field):
        return default
    return req_enum(payload, field, choices)


def _as_decimal(payload, field):
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        _bad(field, "must be a number")
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _bad(field, "must be a number")
    if not dec.is_finite():
        _bad(field, "must be a finite number")
    return dec


def req_num(payload, field, places, minimum=None, maximum=None,
            exclusive_min=False, exclusive_max=False):
    if not _present(payload, field):
        _bad(field, "is required")
    dec = _as_decimal(payload, field)
    _range_check(field, dec, minimum, maximum, exclusive_min, exclusive_max)
    return quant(dec, places)


def opt_num(payload, field, places, minimum=None, maximum=None,
            exclusive_min=False, exclusive_max=False, default=None):
    if not _present(payload, field):
        return default
    return req_num(payload, field, places, minimum, maximum, exclusive_min, exclusive_max)


def _range_check(field, dec, minimum, maximum, exclusive_min, exclusive_max):
    if minimum is not None:
        if exclusive_min and dec <= Decimal(str(minimum)):
            _bad(field, "must be strictly greater than %s" % minimum)
        if not exclusive_min and dec < Decimal(str(minimum)):
            _bad(field, "must be at least %s" % minimum)
    if maximum is not None:
        if exclusive_max and dec >= Decimal(str(maximum)):
            _bad(field, "must be strictly less than %s" % maximum)
        if not exclusive_max and dec > Decimal(str(maximum)):
            _bad(field, "must be at most %s" % maximum)


def quant(dec, places):
    from calc import q
    return q(dec, places)


def req_int(payload, field, minimum=None, maximum=None):
    if not _present(payload, field):
        _bad(field, "is required")
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be at most %d" % maximum)
    return value


def opt_int(payload, field, minimum=None, maximum=None, default=None):
    if not _present(payload, field):
        return default
    return req_int(payload, field, minimum, maximum)


def req_bool(payload, field):
    if not _present(payload, field):
        _bad(field, "is required")
    value = payload[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def opt_bool(payload, field, default=None):
    if not _present(payload, field):
        return default
    return req_bool(payload, field)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def parse_date_str(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return datetime.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def req_date(payload, field):
    if not _present(payload, field):
        _bad(field, "is required")
    parsed = parse_date_str(payload[field])
    if parsed is None:
        _bad(field, "must be a well-formed YYYY-MM-DD date")
    return payload[field], parsed


def opt_date(payload, field):
    if not _present(payload, field):
        return None, None
    return req_date(payload, field)


def req_month(payload, field):
    value = req_str(payload, field)
    if not _MONTH_RE.match(value):
        _bad(field, "must be a well-formed YYYY-MM month")
    return value


def must_be_absent(payload, field, why):
    if _present(payload, field):
        _bad(field, why)


# --------------------------------------------------------------------------
# rung 8: pagination
# --------------------------------------------------------------------------
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)


# --------------------------------------------------------------------------
# rungs 5 and 6: existence
# --------------------------------------------------------------------------
def _find(collection, key, error_id):
    if not isinstance(key, str):
        raise ApiError(error_id)
    row = collection.get(key)
    if row is None:
        raise ApiError(error_id)
    return row


def get_tract(tract_id):
    return _find(db.tracts, tract_id, "ERR_TRACT_NOT_FOUND")


def get_owner(owner_id):
    return _find(db.royalty_owners, owner_id, "ERR_ROYALTY_OWNER_NOT_FOUND")


def get_interest(interest_id):
    return _find(db.mineral_interests, interest_id, "ERR_MINERAL_INTEREST_NOT_FOUND")


def get_valuation(valuation_id):
    return _find(db.valuations, valuation_id, "ERR_VALUATION_NOT_FOUND")


def get_offer(offer_id):
    return _find(db.offer_letters, offer_id, "ERR_OFFER_LETTER_NOT_FOUND")


def get_psa(psa_id):
    return _find(db.psas, psa_id, "ERR_PSA_NOT_FOUND")


def get_defect(defect_id):
    return _find(db.title_defects, defect_id, "ERR_TITLE_DEFECT_NOT_FOUND")


def get_unit(unit_id):
    return _find(db.units, unit_id, "ERR_UNIT_NOT_FOUND")


def get_allocation(allocation_id):
    return _find(db.allocations, allocation_id, "ERR_ALLOCATION_NOT_FOUND")


def get_order(order_id):
    return _find(db.division_orders, order_id, "ERR_DIVISION_ORDER_NOT_FOUND")


def get_detail(detail_id):
    return _find(db.revenue_details, detail_id, "ERR_REVENUE_DETAIL_NOT_FOUND")


def get_suspense(account_id):
    return _find(db.suspense_accounts, account_id, "ERR_SUSPENSE_ACCOUNT_NOT_FOUND")


def body_ref(payload, field, collection, error_id):
    """Rung 6: a reference supplied in the body must resolve before any business
    rule is evaluated.  A missing / non-string value falls through to the rung 7
    shape check instead."""
    value = payload.get(field)
    if isinstance(value, str):
        row = collection.get(value)
        if row is None:
            raise ApiError(error_id)
        return row
    return None
