"""Request body parsing and field-constraint validation helpers.

Missing/ill-typed/out-of-range fields surface as ERR_FIELD_CONSTRAINT_VIOLATION
(400) — validation priority 11; body foreign-key misses surface separately as
ERR_REFERENCED_RESOURCE_NOT_FOUND (422, priority 4).
"""

from flask import request

import db
from errors import ApiError


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _fail(field, detail):
    raise ApiError("ERR_FIELD_CONSTRAINT_VIOLATION",
                   f"Field '{field}': {detail}", 400)


def req_present(data, field):
    if field not in data or data[field] is None:
        _fail(field, "is required")
    return data[field]


def req_str(data, field):
    v = req_present(data, field)
    if not isinstance(v, str) or not v.strip():
        _fail(field, "must be a non-empty string")
    return v


def opt_str(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, str):
        _fail(field, "must be a string")
    return v


def req_int(data, field):
    v = req_present(data, field)
    if isinstance(v, bool) or not isinstance(v, int):
        _fail(field, "must be an integer")
    return v


def opt_int(data, field, default=None):
    v = data.get(field, default)
    if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
        _fail(field, "must be an integer")
    return v


def req_bool(data, field):
    v = req_present(data, field)
    if not isinstance(v, bool):
        _fail(field, "must be a boolean")
    return v


def opt_bool(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, bool):
        _fail(field, "must be a boolean")
    return v


def req_enum(data, field, allowed):
    v = req_present(data, field)
    if v not in allowed:
        _fail(field, f"must be one of {sorted(allowed)}")
    return v


def opt_enum(data, field, allowed, default=None):
    v = data.get(field, default)
    if v not in allowed:
        _fail(field, f"must be one of {sorted(allowed)}")
    return v


def req_dt(data, field):
    """Required ISO 8601 datetime; returned canonical-rendered."""
    v = req_present(data, field)
    if not isinstance(v, str):
        _fail(field, "must be an ISO 8601 datetime string")
    try:
        return db.render_dt(db.parse_dt(v))
    except (ValueError, TypeError):
        _fail(field, "must be an ISO 8601 datetime string")


def opt_dt(data, field, default=None):
    v = data.get(field, default)
    if v is None:
        return None
    if not isinstance(v, str):
        _fail(field, "must be an ISO 8601 datetime string")
    try:
        return db.render_dt(db.parse_dt(v))
    except (ValueError, TypeError):
        _fail(field, "must be an ISO 8601 datetime string")


def ref_not_found(detail):
    raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", detail, 422)
