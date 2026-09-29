"""HTTP plumbing: envelope, auth decorator, structural validation, pagination."""
import functools
from decimal import Decimal, InvalidOperation

from flask import g, jsonify, request

import store
from core import (
    ApiError, D, fail, parse_date, parse_datetime, request_id, wall_now_str,
)

COORDINATOR = "SubrecipientCoordinator"


# --------------------------------------------------------------------------
# Envelope
# --------------------------------------------------------------------------

def _plain(value):
    if isinstance(value, Decimal):
        f = float(value)
        return f
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _meta(extra=None):
    meta = {"api_request_id": request_id(), "api_request_timestamp": wall_now_str()}
    if extra:
        meta.update(extra)
    return meta


def respond_object(record, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _plain(store.serialize(record) if "_kind" in record else record),
    }
    return jsonify(body), status


def respond_raw(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": _plain(data)}
    return jsonify(body), status


def respond_list(records, limit, offset, total_count):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(records) < total_count,
        }),
        "response_type": "array",
        "data": [_plain(store.serialize(r)) for r in records],
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


def raw_error(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

def endpoint(*roles):
    allowed = set(roles) if roles else set(store.ALL_ROLES)

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            if uid is None or uid.strip() == "":
                fail("ERR_UNAUTHENTICATED")
            role = request.headers.get("X-User-Role")
            if role is None or role not in allowed:
                fail("ERR_UNAUTHORIZED")
            g.uid = uid
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def scope_project(project_id):
    """Project-scoped ownership check for the SubrecipientCoordinator role."""
    if g.get("role") == COORDINATOR and project_id is not None and g.get("uid") != project_id:
        fail("ERR_UNAUTHORIZED")


def scope_parcel(parcel):
    if parcel is not None:
        scope_project(parcel.get("project_id"))


# --------------------------------------------------------------------------
# Body access + structural validation
# --------------------------------------------------------------------------

def get_body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _bad(name, why):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, why))


def present(body, name):
    return name in body and body[name] is not None


def req_string(body, name, allow_empty=False):
    if not present(body, name):
        _bad(name, "is required")
    value = body[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if not allow_empty and value.strip() == "":
        _bad(name, "must not be empty")
    return value


def opt_string(body, name, default=None, allow_empty=True):
    if not present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if not allow_empty and value.strip() == "":
        _bad(name, "must not be empty")
    return value


def req_enum(body, name, choices):
    value = req_string(body, name)
    if value not in choices:
        _bad(name, "must be one of %s" % ", ".join(choices))
    return value


def opt_enum(body, name, choices, default=None):
    if not present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if value not in choices:
        _bad(name, "must be one of %s" % ", ".join(choices))
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(body, name):
    if not present(body, name):
        _bad(name, "is required")
    value = body[name]
    if not _is_int(value):
        _bad(name, "must be an integer")
    return value


def opt_int(body, name, default=None):
    if not present(body, name):
        return default
    value = body[name]
    if not _is_int(value):
        _bad(name, "must be an integer")
    return value


def req_cents(body, name):
    value = req_int(body, name)
    if value < 0:
        _bad(name, "must not be negative")
    return value


def opt_cents(body, name, default=0):
    if not present(body, name):
        return default
    value = opt_int(body, name)
    if value < 0:
        _bad(name, "must not be negative")
    return value


def _to_decimal(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        _bad(name, "must be a number")
    if isinstance(value, str):
        _bad(name, "must be a number")
    try:
        return D(value)
    except (InvalidOperation, ValueError):
        _bad(name, "must be a number")


def req_number(body, name):
    if not present(body, name):
        _bad(name, "is required")
    return _to_decimal(name, body[name])


def opt_number(body, name, default=None):
    if not present(body, name):
        return default
    return _to_decimal(name, body[name])


def check_places(name, value, places):
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > places:
        _bad(name, "must carry at most %d decimal places" % places)
    return value


def decimal_field(body, name, required=True, default=None, places=None,
                  minimum=None, maximum=None, exclusive_min=False, exclusive_max=False):
    if not present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = _to_decimal(name, body[name])
    if places is not None:
        check_places(name, value, places)
    if minimum is not None:
        if exclusive_min and value <= minimum:
            _bad(name, "must be greater than %s" % minimum)
        if not exclusive_min and value < minimum:
            _bad(name, "must be at least %s" % minimum)
    if maximum is not None:
        if exclusive_max and value >= maximum:
            _bad(name, "must be less than %s" % maximum)
        if not exclusive_max and value > maximum:
            _bad(name, "must be at most %s" % maximum)
    return value


def int_field(body, name, required=True, default=None, minimum=None, maximum=None):
    if not present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not _is_int(value):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %d" % maximum)
    return value


def req_bool(body, name):
    if not present(body, name):
        _bad(name, "is required")
    if not isinstance(body[name], bool):
        _bad(name, "must be a boolean")
    return body[name]


def opt_bool(body, name, default=False):
    if not present(body, name):
        return default
    if not isinstance(body[name], bool):
        _bad(name, "must be a boolean")
    return body[name]


def req_date(body, name):
    raw = req_string(body, name)
    parsed = parse_date(raw)
    if parsed is None:
        _bad(name, "must be a date in YYYY-MM-DD form")
    return parsed


def opt_date(body, name, default=None):
    if not present(body, name):
        return default
    raw = body[name]
    if not isinstance(raw, str):
        _bad(name, "must be a string")
    parsed = parse_date(raw)
    if parsed is None:
        _bad(name, "must be a date in YYYY-MM-DD form")
    return parsed


def req_dt(body, name):
    raw = req_string(body, name)
    parsed = parse_datetime(raw)
    if parsed is None:
        _bad(name, "must be an ISO 8601 UTC datetime")
    return parsed


def opt_id(body, name):
    """Optional foreign-key reference: must be a non-empty string when supplied."""
    if not present(body, name):
        return None
    value = body[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if value.strip() == "":
        _bad(name, "must not be empty")
    return value


# --------------------------------------------------------------------------
# Query parameters
# --------------------------------------------------------------------------

def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


def query_enum(name, choices):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in choices:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(choices)))
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "%s must be a boolean." % name)


def query_str(name):
    return request.args.get(name)


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total


def list_response(records, sort=None):
    limit, offset = pagination()
    ordered = sorted(records, key=sort or store.sort_key)
    page, total = paginate(ordered, limit, offset)
    return respond_list(page, limit, offset, total)
