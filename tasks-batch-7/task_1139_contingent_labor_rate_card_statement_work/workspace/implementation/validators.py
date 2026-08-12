"""Request body parsing, field validators, and pagination helpers.

Request-shape violations yield ERR_VALIDATION (400). Computed or
system-owned fields supplied in a request body are ignored silently.
Dates are YYYY-MM-DD strings; hours are decimals with at most 2dp.
"""

import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ERR_VALIDATION, raise_err

_MISSING = object()
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw) == 0:
        return {}
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        raise_err(ERR_VALIDATION, "Request body must be a valid JSON object.")
    if not isinstance(body, dict):
        raise_err(ERR_VALIDATION, "Request body must be a JSON object.")
    return body


def _present(body, field):
    v = body.get(field, _MISSING)
    if v is _MISSING or v is None:
        return None
    return v


def req_str(body, field):
    v = _present(body, field)
    if v is None or not isinstance(v, str):
        raise_err(ERR_VALIDATION, f"Field '{field}' is required and must be a string.")
    return v


def opt_str(body, field, default=None):
    v = _present(body, field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise_err(ERR_VALIDATION, f"Field '{field}' must be a string.")
    return v


def req_int(body, field):
    v = _present(body, field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_VALIDATION, f"Field '{field}' is required and must be an integer.")
    return v


def opt_int(body, field, default=None):
    v = _present(body, field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_VALIDATION, f"Field '{field}' must be an integer.")
    return v


def req_num(body, field):
    """A JSON number (int or float), returned as supplied."""
    v = _present(body, field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_err(ERR_VALIDATION, f"Field '{field}' is required and must be a number.")
    return v


def opt_num(body, field, default=None):
    v = _present(body, field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_err(ERR_VALIDATION, f"Field '{field}' must be a number.")
    return v


def req_bool(body, field):
    v = _present(body, field)
    if v is None or not isinstance(v, bool):
        raise_err(ERR_VALIDATION, f"Field '{field}' is required and must be a boolean.")
    return v


def opt_bool(body, field, default=None):
    v = _present(body, field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise_err(ERR_VALIDATION, f"Field '{field}' must be a boolean.")
    return v


def req_date(body, field):
    v = _present(body, field)
    if v is None or not isinstance(v, str) or not _DATE_RE.match(v):
        raise_err(ERR_VALIDATION, f"Field '{field}' is required and must be a YYYY-MM-DD date.")
    try:
        date.fromisoformat(v)
    except ValueError:
        raise_err(ERR_VALIDATION, f"Field '{field}' is not a valid calendar date.")
    return v


def opt_date(body, field, default=None):
    v = _present(body, field)
    if v is None:
        return default
    if not isinstance(v, str) or not _DATE_RE.match(v):
        raise_err(ERR_VALIDATION, f"Field '{field}' must be a YYYY-MM-DD date.")
    try:
        date.fromisoformat(v)
    except ValueError:
        raise_err(ERR_VALIDATION, f"Field '{field}' is not a valid calendar date.")
    return v


def req_enum(body, field, allowed):
    v = _present(body, field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_err(
            ERR_VALIDATION,
            f"Field '{field}' is required and must be one of {sorted(allowed)}.",
        )
    return v


def _to_decimal_hours(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_err(ERR_VALIDATION, f"Field '{field}' must be a number.")
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        raise_err(ERR_VALIDATION, f"Field '{field}' must be a number.")
    if d.as_tuple().exponent < -2:
        raise_err(ERR_VALIDATION, f"Field '{field}' must carry at most two decimal places.")
    if d < 0:
        raise_err(ERR_VALIDATION, f"Field '{field}' must not be negative.")
    return d


def req_hours(body, field):
    """Hours: decimal with at most two decimal places. Returns the raw JSON value."""
    v = _present(body, field)
    if v is None:
        raise_err(ERR_VALIDATION, f"Field '{field}' is required.")
    _to_decimal_hours(v, field)
    return v


def opt_hours(body, field, default=None):
    v = _present(body, field)
    if v is None:
        return default
    _to_decimal_hours(v, field)
    return v


def hours_decimal(v):
    return Decimal(str(v))


def parse_iso8601(s):
    """Tolerant ISO 8601 parser for the logical clock; returns an aware UTC datetime."""
    if not isinstance(s, str) or not s:
        raise_err(ERR_VALIDATION, "Field 'to_iso8601' is required and must be an ISO 8601 timestamp.")
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise_err(ERR_VALIDATION, f"'{s}' is not a valid ISO 8601 timestamp.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _query_int(name, default):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise_err(ERR_VALIDATION, f"Query parameter '{name}' must be an integer.")


def paginate(records, serialize):
    """Sort by created_at ASC (insertion order as tie-break), then page.

    limit defaults to 10 (clamped to [1, 100]); offset defaults to 0
    (clamped to >= 0).
    """
    limit = _query_int("limit", 10)
    offset = _query_int("offset", 0)
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    ordered = sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return [serialize(r) for r in page], total, limit, offset


def apply_filters(records, filters):
    """Exact-match filters; only non-None query values filter."""
    out = []
    for rec in records:
        ok = True
        for field, value in filters.items():
            if value is not None and rec.get(field) != value:
                ok = False
                break
        if ok:
            out.append(rec)
    return out
