"""Rank-20 request-shape helpers (PRD 2.7).

Everything raised from here is ERR_INVALID_REQUEST / 400.
"""

from decimal import Decimal, InvalidOperation

from flask import request

import clock
import db
import errors


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return payload


def present(payload, name):
    return name in payload and payload[name] is not None


def req_str(payload, name):
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise errors.invalid_request("'%s' must be a non-empty string." % name)
    return value


def opt_str(payload, name, default=None):
    if not present(payload, name):
        return default
    value = payload.get(name)
    if not isinstance(value, str):
        raise errors.invalid_request("'%s' must be a string." % name)
    return value


def req_enum(payload, name, allowed):
    value = req_str(payload, name)
    if value not in allowed:
        raise errors.invalid_request(
            "'%s' must be one of %s." % (name, ", ".join(allowed))
        )
    return value


def opt_enum(payload, name, allowed, default=None):
    if not present(payload, name):
        return default
    return req_enum(payload, name, allowed)


def req_int(payload, name, minimum=None, maximum=None):
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.invalid_request("'%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise errors.invalid_request("'%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise errors.invalid_request("'%s' must be <= %s." % (name, maximum))
    return value


def req_num(payload, name, minimum=None, maximum=None):
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.invalid_request("'%s' must be a number." % name)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise errors.invalid_request("'%s' must be a number." % name)
    if minimum is not None and dec < Decimal(str(minimum)):
        raise errors.invalid_request("'%s' must be >= %s." % (name, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        raise errors.invalid_request("'%s' must be <= %s." % (name, maximum))
    return float(value)


def req_date(payload, name):
    value = clock.parse_date(payload.get(name))
    if value is None:
        raise errors.invalid_request("'%s' must be a YYYY-MM-DD date." % name)
    return value


def opt_date(payload, name):
    if not present(payload, name):
        return None
    return req_date(payload, name)


def req_datetime(payload, name):
    value = clock.parse_datetime(payload.get(name))
    if value is None:
        raise errors.invalid_request("'%s' must be an ISO 8601 instant." % name)
    return value


def opt_datetime(payload, name):
    if not present(payload, name):
        return None
    return req_datetime(payload, name)


def req_id(payload, name):
    """A reference identifier must at least be a non-empty string (rank 20)."""
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise errors.invalid_request("'%s' must be a non-empty string." % name)
    return value


def opt_id(payload, name):
    if not present(payload, name):
        return None
    return req_id(payload, name)


# --------------------------------------------------------------------------
# Reference resolution (ranks 10-14)
# --------------------------------------------------------------------------

_NOT_FOUND = {
    "sites": ("ERR_SITE_NOT_FOUND", 404),
    "operators": ("ERR_OPERATOR_NOT_FOUND", 404),
    "devices": ("ERR_DEVICE_NOT_FOUND", 404),
    "lots": ("ERR_REAGENT_LOT_NOT_FOUND", 404),
}


def not_found(table):
    error_id, status = _NOT_FOUND.get(table, ("ERR_RESOURCE_NOT_FOUND", 404))
    return errors.ApiError(error_id, status)


def resolve(table, row_id):
    row = db.get(table, row_id)
    if row is None:
        raise not_found(table)
    return row


def resolve_body(table, payload, name):
    """Rank 20 for a missing field, then the table's own not-found rank."""
    value = req_id(payload, name)
    return resolve(table, value)


def resolve_body_optional(table, payload, name):
    if not present(payload, name):
        return None
    return resolve_body(table, payload, name)


# --------------------------------------------------------------------------
# Pagination + filters (PRD 2.3)
# --------------------------------------------------------------------------

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("'offset' must be an integer.")
        if offset < 0:
            raise errors.invalid_request("'offset' must be >= 0.")
    return limit, offset


def page(items, limit, offset):
    return items[offset:offset + limit]


def arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
