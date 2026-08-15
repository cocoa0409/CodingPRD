"""Request parsing / field validation helpers and datetime formatting.

All well-formedness failures raise ERR_INVALID_REQUEST (400), per PRD §2.7 tier 3.
"""
import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", message, 400)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid("Request body must be a JSON object.")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str):
        invalid("Field '%s' is required and must be a string." % field)
    return v


def req_int(data, field, minimum=None, maximum=None):
    v = data.get(field)
    if not _is_int(v):
        invalid("Field '%s' is required and must be an integer." % field)
    if minimum is not None and v < minimum:
        invalid("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and v > maximum:
        invalid("Field '%s' must be <= %s." % (field, maximum))
    return v


def opt_int(data, field, minimum=None, maximum=None):
    if field not in data or data.get(field) is None:
        return None
    return req_int(data, field, minimum=minimum, maximum=maximum)


def req_number(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        invalid("Field '%s' is required and must be a number." % field)
    return v


def parse_dt(value):
    """Parse an ISO 8601 datetime; naive values are treated as UTC.
    Returns an aware UTC datetime, or None when unparseable."""
    if not isinstance(value, str):
        return None
    t = value.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(data, field):
    v = data.get(field)
    dt = parse_dt(v)
    if dt is None:
        invalid("Field '%s' is required and must be an ISO 8601 datetime." % field)
    return dt


def opt_datetime(data, field):
    if field not in data or data.get(field) is None:
        return None
    return req_datetime(data, field)


def parse_date_strict(value):
    """Strict YYYY-MM-DD date parse. Returns a date or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def req_date(data, field):
    v = data.get(field)
    d = parse_date_strict(v)
    if d is None:
        invalid("Field '%s' is required and must be a YYYY-MM-DD date." % field)
    return d


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def pagination_params():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0 (min 0).
    Out-of-range values are clamped; non-numeric values are malformed (400)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid("Query parameter 'limit' must be an integer.")
        limit = max(1, min(100, limit))
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid("Query parameter 'offset' must be an integer.")
        offset = max(0, offset)
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset : offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
