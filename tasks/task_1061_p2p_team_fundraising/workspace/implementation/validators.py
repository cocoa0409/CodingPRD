"""Request-shape validation (PRD 2.8 step 3) and pagination parsing."""
from flask import request

import config
import db
from errors import raise_error


def _bad(msg):
    raise_error("ERR_INVALID_REQUEST", msg)


def get_body(required=False):
    if request.content_length in (None, 0) and not request.data:
        if required:
            return {}
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        _bad("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        _bad("Request body must be a JSON object.")
    return body


def present(body, field):
    return field in body and body[field] is not None


# ------------------------------------------------------------------ strings
def req_str(body, field):
    if not present(body, field):
        _bad("Field '%s' is required." % field)
    value = body[field]
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % field)
    return value


def opt_str(body, field, default=None):
    if not present(body, field):
        return default
    value = body[field]
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % field)
    return value


# ----------------------------------------------------------------- integers
def _check_int(field, value, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        _bad("Field '%s' must be at least %d." % (field, minimum))
    if maximum is not None and value > maximum:
        _bad("Field '%s' must be at most %d." % (field, maximum))
    return value


def req_int(body, field, minimum=None, maximum=None):
    if not present(body, field):
        _bad("Field '%s' is required." % field)
    return _check_int(field, body[field], minimum, maximum)


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if not present(body, field):
        return default
    return _check_int(field, body[field], minimum, maximum)


# ------------------------------------------------------------------ numbers
def req_number(body, field, gt=None, lte=None):
    if not present(body, field):
        _bad("Field '%s' is required." % field)
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("Field '%s' must be a number." % field)
    if gt is not None and not value > gt:
        _bad("Field '%s' must be greater than %s." % (field, gt))
    if lte is not None and not value <= lte:
        _bad("Field '%s' must be at most %s." % (field, lte))
    return value


# ----------------------------------------------------------------- booleans
def opt_bool(body, field, default=False):
    if not present(body, field):
        return default
    value = body[field]
    if not isinstance(value, bool):
        _bad("Field '%s' must be a boolean." % field)
    return value


# -------------------------------------------------------------------- enums
def req_enum(body, field, allowed):
    value = req_str(body, field)
    if value not in allowed:
        _bad("Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


# ---------------------------------------------------------------- datetimes
def req_dt(body, field):
    value = req_str(body, field)
    parsed = db.parse_iso(value)
    if parsed is None:
        _bad("Field '%s' must be an ISO 8601 instant." % field)
    return parsed


def opt_dt(body, field, default=None):
    if not present(body, field):
        return default
    return req_dt(body, field)


# --------------------------------------------------------------- pagination
def pagination():
    args = request.args
    limit = config.PAGINATION_DEFAULT_LIMIT
    offset = config.PAGINATION_DEFAULT_OFFSET
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("Query parameter 'limit' must be an integer.")
        if limit < config.PAGINATION_MIN_LIMIT or limit > config.PAGINATION_MAX_LIMIT:
            _bad("Query parameter 'limit' must be between 1 and 100.")
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("Query parameter 'offset' must be an integer.")
        if offset < config.PAGINATION_DEFAULT_OFFSET:
            _bad("Query parameter 'offset' must be at least 0.")
    return limit, offset


def q(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_enum(name, allowed):
    value = q(name)
    if value is None:
        return None
    if value not in allowed:
        _bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value
