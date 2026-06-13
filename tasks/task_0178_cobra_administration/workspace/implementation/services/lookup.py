"""Existence lookups (ERR_NOT_FOUND) and request-body validation helpers.

Validation ordering (PRD §2.9): existence (404) before ownership (403) before
body shape (ERR_INVALID_REQUEST, 400) before state (409).
"""
from db import store
from errors import ApiError
from timeutil import parse_dt, parse_year_month


def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Resource %s not found" % rid)
    return rec


def require_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def require_enum(body, field, allowed, required=True):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return None
    val = body[field]
    if val not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "Invalid value for %s: %r" % (field, val))
    return val


def require_positive_int(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return None
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a positive integer" % field)
    if val <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be greater than zero" % field)
    return val


def require_int(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    return val


def require_number(body, field, required=True, default=None, minimum=None,
                   maximum=None, min_inclusive=True, max_inclusive=True):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a number" % field)
    if minimum is not None:
        if min_inclusive and val < minimum:
            raise ApiError("ERR_INVALID_REQUEST", "%s below minimum" % field)
        if not min_inclusive and val <= minimum:
            raise ApiError("ERR_INVALID_REQUEST", "%s below minimum" % field)
    if maximum is not None:
        if max_inclusive and val > maximum:
            raise ApiError("ERR_INVALID_REQUEST", "%s above maximum" % field)
        if not max_inclusive and val >= maximum:
            raise ApiError("ERR_INVALID_REQUEST", "%s above maximum" % field)
    return val


def require_string(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return None
    val = body[field]
    if not isinstance(val, str) or val.strip() == "":
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a non-empty string" % field)
    return val


def require_datetime(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return None
    try:
        return parse_dt(body[field])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 datetime" % field)


def require_coverage_month(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return None
    val = body[field]
    try:
        parse_year_month(val)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a YYYY-MM string" % field)
    return val


def paginate(query_args, items):
    """Apply limit/offset pagination over a list already sorted ascending by
    creation. Returns (page_items, limit, offset, total_count)."""
    total = len(items)
    limit = _parse_pagination_int(query_args.get("limit"), default=10, lo=1, hi=100)
    offset = _parse_pagination_int(query_args.get("offset"), default=0, lo=0, hi=None)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def _parse_pagination_int(raw, default, lo, hi):
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        return default
    if val < lo:
        val = lo
    if hi is not None and val > hi:
        val = hi
    return val


def sorted_by_creation(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
