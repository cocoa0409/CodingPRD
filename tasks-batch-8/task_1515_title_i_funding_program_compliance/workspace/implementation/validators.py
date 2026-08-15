"""Body parsing and schema-validation helpers (tier 4) plus pagination.

All type/shape failures raise ERR_INVALID_REQUEST unless a more specific
error id (ERR_INVALID_DATE_RANGE / ERR_NARRATIVE_TOO_SHORT) applies.
"""

from datetime import date, datetime, timezone

from flask import request

import errors


def json_body():
    """Return the request JSON object; an absent/unparseable body is {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        errors.fail(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return data


def check_unknown(data, allowed):
    extra = [k for k in data.keys() if k not in allowed]
    if extra:
        errors.fail(
            errors.ERR_INVALID_REQUEST,
            "Unknown or read-only field(s) supplied: %s." % ", ".join(sorted(extra)),
        )


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(data, field):
    v = data.get(field)
    if v is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: %s." % field)
    if not isinstance(v, str) or v == "":
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be a non-empty string." % field)
    return v


def opt_str(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be a string." % field)
    return v


def req_int(data, field):
    v = data.get(field)
    if v is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: %s." % field)
    if not _is_int(v):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be an integer." % field)
    return v


def opt_int(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not _is_int(v):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be an integer." % field)
    return v


def opt_bool(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be a boolean." % field)
    return v


def req_enum(data, field, members):
    v = data.get(field)
    if v is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: %s." % field)
    if not isinstance(v, str) or v not in members:
        errors.fail(
            errors.ERR_INVALID_REQUEST,
            "Field %s must be one of: %s." % (field, ", ".join(sorted(members))),
        )
    return v


def opt_enum(data, field, members, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v not in members:
        errors.fail(
            errors.ERR_INVALID_REQUEST,
            "Field %s must be one of: %s." % (field, ", ".join(sorted(members))),
        )
    return v


def req_date(data, field):
    """Required ISO date string field -> datetime.date."""
    v = req_str(data, field)
    return parse_date(v, field)


def parse_date(v, field):
    if not isinstance(v, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be an ISO date string." % field)
    try:
        return date.fromisoformat(v)
    except ValueError:
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be a valid ISO date." % field)


def parse_instant(v, field):
    """Parse an ISO 8601 instant; naive values are read as UTC."""
    if not isinstance(v, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be an ISO 8601 string." % field)
    text = v.strip()
    try:
        if text.endswith("Z") or text.endswith("z"):
            dt = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            d = date.fromisoformat(text)
            dt = datetime(d.year, d.month, d.day)
        except ValueError:
            errors.fail(
                errors.ERR_INVALID_REQUEST,
                "Field %s must be a valid ISO 8601 instant." % field,
            )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_array(data, field):
    v = data.get(field)
    if v is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: %s." % field)
    if not isinstance(v, list):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be an array." % field)
    return v


def opt_array(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, list):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be an array." % field)
    return v


# --- pagination -------------------------------------------------------------
def pagination_params():
    """limit (default 10, 1..100) and offset (default 0, >=0)."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            errors.fail(errors.ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < 1 or limit > 100:
            errors.fail(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100.")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            errors.fail(errors.ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            errors.fail(errors.ERR_INVALID_REQUEST, "offset must be >= 0.")
    return limit, offset


def query_filter(name):
    return request.args.get(name)


def query_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    errors.fail(errors.ERR_INVALID_REQUEST, "Query parameter %s must be true or false." % name)


def query_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        errors.fail(errors.ERR_INVALID_REQUEST, "Query parameter %s must be an integer." % name)


def sorted_page(store_values, filters):
    """Apply exact-match filters, sort by created_at ASC, then paginate."""
    rows = [v for v in store_values]
    for key, expected in filters:
        if expected is not None:
            rows = [r for r in rows if r.get(key) == expected]
    rows.sort(key=lambda r: r["created_at"])
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, limit, offset, total
