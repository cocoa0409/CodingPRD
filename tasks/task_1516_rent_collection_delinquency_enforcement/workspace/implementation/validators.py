"""Body parsing and schema-validation helpers plus pagination (PRD 2.3, 2.9).

Type/shape failures raise ERR_INVALID_REQUEST. Calendar dates are strict
YYYY-MM-DD strings; datetimes are ISO 8601 (PRD 2.4).
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


def parse_date(v, field):
    if not isinstance(v, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be an ISO date string." % field)
    try:
        return date.fromisoformat(v)
    except ValueError:
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be a valid YYYY-MM-DD date." % field)


def req_date(data, field):
    """Required YYYY-MM-DD string field -> datetime.date."""
    return parse_date(req_str(data, field), field)


def opt_date(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    return parse_date(v, field)


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


def req_id_array(data, field):
    """Required non-empty array of id strings (e.g. charge_ids)."""
    v = data.get(field)
    if v is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: %s." % field)
    if not isinstance(v, list) or len(v) == 0:
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be a non-empty array." % field)
    for item in v:
        if not isinstance(item, str):
            errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must contain id strings." % field)
    return list(v)


def req_version(data, field):
    """OCC field expected_lease_version: non-optional integer (PRD 2.8)."""
    v = data.get(field)
    if not _is_int(v):
        errors.fail(
            errors.ERR_INVALID_REQUEST,
            "Field %s is required and must be an integer lease version." % field,
        )
    return v


# --- pagination --------------------------------------------------------------
def pagination_params():
    """limit (default 10, 1..100) and offset (default 0, >= 0) — PRD 2.3."""
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


def sorted_page(rows, filters, limit=None, offset=None):
    """Apply exact-match filters, sort by created_at ascending (PRD 2.3),
    then paginate. `filters` is a list of (field, value-or-None)."""
    for key, expected in filters:
        if expected is not None:
            rows = [r for r in rows if r.get(key) == expected]
    rows = sorted(rows, key=lambda r: r["created_at"])
    if limit is None:
        limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, limit, offset, total
