"""Shared helpers: pagination, datetime parsing, day arithmetic, validation."""
from datetime import datetime, timezone

from flask import request

from errors import err

MS_PER_DAY = 86400000


def parse_pagination():
    """Read limit/offset from query string per PRD §2.3.

    limit default 10, min 1, max 100. offset default 0.
    Malformed values -> ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            offset = 0

    return limit, offset


def paginate(rows, limit, offset):
    """rows already sorted; return (page, total_count)."""
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total


def sort_by_created(rows):
    """Sort by creation order ascending using the internal sequence."""
    return sorted(rows, key=lambda r: r["_seq"])


def parse_iso8601(value, field="value"):
    """Parse an ISO 8601 string into a timezone-aware UTC datetime."""
    if not isinstance(value, str) or not value:
        raise err("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 string.")
    s = value
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"{field} is not a valid ISO 8601 timestamp.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_epoch_ms(dt):
    return int(dt.timestamp() * 1000)


def iso_from_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_days_iso(iso_value, days):
    """Add whole UTC days (86_400_000 ms each) to an ISO timestamp; return ISO."""
    dt = parse_iso8601(iso_value)
    ms = to_epoch_ms(dt) + days * MS_PER_DAY
    out = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return iso_from_dt(out)


def days_remaining(expiration_iso, current_iso):
    """floor((expiration - current) / MS_PER_DAY) toward -inf."""
    exp_ms = to_epoch_ms(parse_iso8601(expiration_iso))
    cur_ms = to_epoch_ms(parse_iso8601(current_iso))
    diff = exp_ms - cur_ms
    # floor division in Python already truncates toward -inf
    return diff // MS_PER_DAY


def require_body():
    """Return JSON body dict, or {} if absent. Reject malformed JSON."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # No body or unparseable; treat absent body as empty dict.
        if request.data:
            raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def nonempty_str(value):
    return isinstance(value, str) and value.strip() != ""
