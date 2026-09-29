"""Request-shape validation (rejection ladder priority 3) plus pagination and
filter parsing (priority 6 / priority 3)."""

import re
from decimal import Decimal, InvalidOperation

from flask import request

import db
from errors import fail
from response import (LIMIT_DEFAULT, LIMIT_MAX, LIMIT_MIN, OFFSET_DEFAULT,
                      OFFSET_MIN)
from timeutil import parse_date, parse_datetime

JURISDICTION_RE = re.compile(r"^[A-Z]{2}$")
INT_FILTER = object()
MISSING = object()


def body():
    raw = request.get_json(silent=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return raw


def _present(payload, field, required):
    if field not in payload or payload[field] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
        return False
    return True


def string_field(payload, field, min_len=1, max_len=None, required=True,
                 default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % field)
    if min_len >= 1 and not value.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must not be blank." % field)
    if len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too short." % field)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too long." % field)
    return value


def id_field(payload, field, required=True, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an identifier." % field)
    return value


def enum_field(payload, field, allowed, required=True, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be one of %s." % (field, ", ".join(sorted(allowed))))
    return value


def int_field(payload, field, minimum=0, maximum=None, required=True,
              default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    if isinstance(value, float):
        if value != int(value):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
        value = int(value)
    if not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is below the minimum." % field)
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is above the maximum." % field)
    return value


def bool_field(payload, field, required=True, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field)
    return value


def unit_decimal_field(payload, field, required=True, default=None):
    """A matcher sub-score: a decimal from 0 through 1 inclusive, carried to
    four decimal places."""
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be numeric." % field)
    try:
        if isinstance(value, float):
            number = Decimal(repr(value))
        elif isinstance(value, (int, str)):
            number = Decimal(str(value).strip())
        else:
            raise InvalidOperation()
    except (InvalidOperation, ValueError, ArithmeticError):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be numeric." % field)
    if not number.is_finite():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be numeric." % field)
    if number < 0 or number > 1:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must fall between 0 and 1 inclusive." % field)
    return number


def jurisdiction_field(payload, field, required=True, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if not isinstance(value, str) or not JURISDICTION_RE.match(value):
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be exactly two uppercase letters." % field)
    return value


def date_field(payload, field, required=True, default=None):
    if not _present(payload, field, required):
        return default
    parsed = parse_date(payload[field])
    if parsed is None:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be an ISO 8601 calendar date." % field)
    return parsed


def datetime_field(payload, field, required=True, default=None):
    if not _present(payload, field, required):
        return default
    parsed = parse_datetime(payload[field])
    if parsed is None:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be an ISO 8601 timestamp." % field)
    return parsed


def pagination():
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if "limit" in request.args:
        raw = request.args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            fail("ERR_INVALID_PAGINATION")
    if "offset" in request.args:
        raw = request.args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION")
        if offset < OFFSET_MIN:
            fail("ERR_INVALID_PAGINATION")
    return limit, offset


def query_filters(spec):
    """spec maps a query parameter name to either an enumeration of accepted
    values, INT_FILTER, or None for free-form identifiers."""
    out = {}
    for name, allowed in spec.items():
        if name not in request.args:
            continue
        raw = request.args.get(name)
        if allowed is INT_FILTER:
            try:
                out[name] = int(str(raw).strip())
            except (TypeError, ValueError):
                fail("ERR_INVALID_REQUEST",
                     "Filter '%s' must be an integer." % name)
        elif allowed is None:
            out[name] = raw
        else:
            if raw not in allowed:
                fail("ERR_INVALID_REQUEST",
                     "Filter '%s' must be one of %s."
                     % (name, ", ".join(sorted(allowed))))
            out[name] = raw
    return out


def apply_filters(rows, selected):
    for field, wanted in selected.items():
        rows = [r for r in rows if r.get(field) == wanted]
    return rows


def paginate(rows):
    limit, offset = pagination()
    total = len(rows)
    return rows[offset:offset + limit], limit, offset, total


NOT_FOUND_BY_TABLE = {
    "brands": "ERR_BRAND_NOT_FOUND",
    "registrations": "ERR_REGISTRATION_NOT_FOUND",
    "enrollments": "ERR_ENROLLMENT_NOT_FOUND",
    "representatives": "ERR_REPRESENTATIVE_NOT_FOUND",
    "sellers": "ERR_SELLER_NOT_FOUND",
    "listings": "ERR_LISTING_NOT_FOUND",
    "claims": "ERR_CLAIM_NOT_FOUND",
    "test_buys": "ERR_TEST_BUY_NOT_FOUND",
    "packages": "ERR_EVIDENCE_PACKAGE_NOT_FOUND",
    "takedowns": "ERR_TAKEDOWN_NOT_FOUND",
    "counter_notices": "ERR_COUNTER_NOTICE_NOT_FOUND",
    "cases": "ERR_CASE_NOT_FOUND",
    "recordations": "ERR_CUSTOMS_RECORDATION_NOT_FOUND",
    "investigations": "ERR_INVESTIGATION_NOT_FOUND",
}


def must_exist(table_name, row_id):
    row = db.get(table_name, row_id)
    if row is None:
        fail(NOT_FOUND_BY_TABLE[table_name])
    return row


def collection(table_name, filter_spec):
    """Filter (priority 3) then paginate (priority 6) a whole family, in the
    canonical created_at ASC / persistence-sequence ASC order."""
    from response import listing, public
    selected = query_filters(filter_spec)
    rows = apply_filters(db.all_rows(table_name), selected)
    page, limit, offset, total = paginate(rows)
    return listing([public(r) for r in page], limit, offset, total)
