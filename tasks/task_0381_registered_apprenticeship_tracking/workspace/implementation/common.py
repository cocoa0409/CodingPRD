"""Shared request-parsing, pagination, and serialization helpers."""
from flask import request

from errors import err

# Internal bookkeeping keys that must never be exposed in API responses.
_INTERNAL_KEYS = {"_seq"}


def get_json_body():
    """Parse the JSON request body. Missing/invalid JSON -> ERR_INVALID_REQUEST.

    An absent body is treated as an empty object so individual field validators
    can raise the precise missing-field error.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or not val.strip():
        raise err("ERR_INVALID_REQUEST", "Field '%s' is required and must be a non-empty string." % field)
    return val


def require_int(body, field, minimum=None):
    val = body.get(field)
    # Reject bools (bool is a subclass of int) and non-integers.
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field '%s' is required and must be an integer." % field)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (field, minimum))
    return val


def require_number(body, field):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field '%s' is required and must be a number." % field)
    return val


def require_enum(body, field, allowed):
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (field, sorted(allowed)))
    return val


def optional_bool(body, field, default=False):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field)
    return val


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3). Invalid -> ERR_INVALID_PAGINATION."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_PAGINATION", "limit must be an integer in 1..100.")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_PAGINATION", "limit must be within 1..100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_PAGINATION", "offset must be an integer >= 0.")
        if offset < 0:
            raise err("ERR_INVALID_PAGINATION", "offset must be >= 0.")

    return limit, offset


def sort_and_paginate(records, limit, offset):
    """Sort by created_at ascending (with _seq tiebreak), then slice."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def serialize(rec):
    """Strip internal bookkeeping keys before returning a record to a client."""
    return {k: v for k, v in rec.items() if k not in _INTERNAL_KEYS}


def serialize_list(records):
    return [serialize(r) for r in records]
