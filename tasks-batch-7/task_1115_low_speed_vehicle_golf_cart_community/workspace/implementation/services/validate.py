"""Stage-1 request-body schema validation helpers.

All required fields present, enums in range, integers within declared ranges,
window end strictly after start. Failure -> ERR_VALIDATION (400).
"""
from datetime import datetime

import db
from errors import err_validation


def body():
    from flask import request
    if not request.is_json:
        raise err_validation("Request body must be JSON")
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err_validation("Request body must be a JSON object")
    return data


def _is_bool(v):
    return isinstance(v, bool)


def require_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise err_validation(f"Field '{field}' must be a non-empty string")
    return v


def optional_str(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err_validation(f"Field '{field}' must be a string")
    return v


def require_int(data, field, min_v=None, max_v=None):
    v = data.get(field)
    if _is_bool(v) or not isinstance(v, int):
        raise err_validation(f"Field '{field}' must be an integer")
    if min_v is not None and v < min_v:
        raise err_validation(f"Field '{field}' below minimum {min_v}")
    if max_v is not None and v > max_v:
        raise err_validation(f"Field '{field}' above maximum {max_v}")
    return v


def optional_int(data, field, min_v=None, max_v=None, default=None):
    v = data.get(field)
    if v is None:
        return default
    if _is_bool(v) or not isinstance(v, int):
        raise err_validation(f"Field '{field}' must be an integer")
    if min_v is not None and v < min_v:
        raise err_validation(f"Field '{field}' below minimum {min_v}")
    if max_v is not None and v > max_v:
        raise err_validation(f"Field '{field}' above maximum {max_v}")
    return v


def require_bool(data, field):
    v = data.get(field)
    if not _is_bool(v):
        raise err_validation(f"Field '{field}' must be a boolean")
    return v


def optional_bool(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not _is_bool(v):
        raise err_validation(f"Field '{field}' must be a boolean")
    return v


def require_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err_validation(f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def require_datetime(data, field):
    v = data.get(field)
    if not isinstance(v, str):
        raise err_validation(f"Field '{field}' must be an ISO 8601 datetime string")
    try:
        return db.parse_ts(v)
    except (ValueError, TypeError):
        raise err_validation(f"Field '{field}' is not a valid ISO 8601 datetime")


def require_date(data, field):
    v = data.get(field)
    if not isinstance(v, str):
        raise err_validation(f"Field '{field}' must be an ISO 8601 date string")
    try:
        return db.parse_date(v)
    except (ValueError, TypeError):
        raise err_validation(f"Field '{field}' is not a valid ISO 8601 date")


def require_window(data, start_field, end_field):
    """Windowed payload: end strictly after start (schema stage)."""
    start = require_datetime(data, start_field)
    end = require_datetime(data, end_field)
    if not end > start:
        raise err_validation(f"'{end_field}' must be strictly after '{start_field}'")
    return start, end


def pagination_args():
    """limit/offset per §2.3: limit default 10, min 1, max 100; offset default 0."""
    from flask import request
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_validation("limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err_validation("offset must be an integer")
        if offset < 0:
            raise err_validation("offset must be >= 0")
    return limit, offset


def sorted_by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total
