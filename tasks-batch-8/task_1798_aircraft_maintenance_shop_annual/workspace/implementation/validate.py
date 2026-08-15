"""Payload shape validation (PRD 2.9 ERR_VALIDATION) and listing helpers.

Malformed input -- a missing required field, an invalid enum value, a part
quantity below one, a labor duration_tenths that is not a positive multiple of
three -- is rejected outright with ERR_VALIDATION (HTTP 400).
"""

from flask import request

import db
import envelope
from errors import ApiError


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def req_present(b, key):
    if key not in b or b[key] is None:
        raise ApiError("ERR_VALIDATION", "Missing required field: %s" % key)
    return b[key]


def req_str(b, key):
    v = req_present(b, key)
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", "Field %s must be a string." % key)
    return v


def opt_str(b, key):
    if key not in b or b[key] is None:
        return None
    v = b[key]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", "Field %s must be a string." % key)
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(b, key):
    v = req_present(b, key)
    if not _is_int(v):
        raise ApiError("ERR_VALIDATION", "Field %s must be an integer." % key)
    return v


def opt_int(b, key, default=None):
    if key not in b or b[key] is None:
        return default
    v = b[key]
    if not _is_int(v):
        raise ApiError("ERR_VALIDATION", "Field %s must be an integer." % key)
    return v


def req_number(b, key):
    v = req_present(b, key)
    if not (_is_int(v) or isinstance(v, float)):
        raise ApiError("ERR_VALIDATION", "Field %s must be a number." % key)
    return v


def req_enum(b, key, members):
    v = req_str(b, key)
    if v not in members:
        raise ApiError(
            "ERR_VALIDATION", "Field %s must be one of %s." % (key, ", ".join(members))
        )
    return v


def req_version(b, key):
    """An OCC expected_*_version field: required, integer (PRD 2.6)."""
    v = req_present(b, key)
    if not _is_int(v):
        raise ApiError("ERR_VALIDATION", "Field %s must be an integer." % key)
    return v


def get_row(table, rid):
    row = table.get(rid)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "Resource not found: %s" % rid)
    return row


def apply_filters(rows, mapping):
    """Exact-match query filters; mapping pairs query params with record keys."""
    for param, key in mapping.items():
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if str(r.get(key)) == value]
    return rows


def paginate(rows, fields=None):
    """limit defaults to 10 (min 1, max 100); offset defaults to 0 (PRD 2.3).
    Rows are raw records; serialization happens after sorting and slicing."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "limit/offset must be integers.")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", "limit must be within [1, 100].")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", "offset must be at least 0.")
    rows = db.sort_rows(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    if fields is not None:
        import ops

        page = [ops.pub(r, fields) for r in page]
    return envelope.listing(page, limit, offset, total)
