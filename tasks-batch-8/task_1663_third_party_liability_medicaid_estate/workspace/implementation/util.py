"""Validation helpers, calendar math, decimal rounding, pagination (PRD §2)."""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --- Request body shape (validation priority 3 -> ERR_INVALID_REQUEST) -------
def body():
    data = request.get_json(silent=True, force=True)
    if data is None or not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return data


def _invalid(msg):
    raise ApiError(ERR_INVALID_REQUEST, msg, 400)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(b, name):
    v = b.get(name)
    if not isinstance(v, str) or not v.strip():
        _invalid("Field '%s' is required and must be a non-empty string" % name)
    return v


def req_int(b, name, minimum=None, exclusive_min=False):
    v = b.get(name)
    if not _is_int(v):
        _invalid("Field '%s' is required and must be an integer" % name)
    if minimum is not None:
        if exclusive_min:
            if v <= minimum:
                _invalid("Field '%s' must be greater than %d" % (name, minimum))
        elif v < minimum:
            _invalid("Field '%s' must be at least %d" % (name, minimum))
    return v


def opt_int_positive(b, name):
    """Optional integer that, when present, must be > 0."""
    if name not in b or b.get(name) is None:
        return None
    v = b.get(name)
    if not _is_int(v) or v <= 0:
        _invalid("Field '%s' must be an integer greater than 0 when present" % name)
    return v


def req_pct(b, name):
    """Fee fraction strictly inside (0, 1)."""
    v = b.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _invalid("Field '%s' is required and must be a number" % name)
    if not (0 < v < 1):
        _invalid("Field '%s' must be strictly between 0 and 1" % name)
    return v


def req_enum(b, name, values):
    v = b.get(name)
    if not isinstance(v, str) or v not in values:
        _invalid("Field '%s' must be one of %s" % (name, ", ".join(values)))
    return v


def req_date(b, name):
    v = b.get(name)
    if not isinstance(v, str) or not DATE_RE.match(v):
        _invalid("Field '%s' is required and must be an ISO date (YYYY-MM-DD)" % name)
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        _invalid("Field '%s' must be a valid calendar date (YYYY-MM-DD)" % name)
    return v


# --- Calendar math (PRD §2.5: all rules read the logical clock) --------------
def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def add_years(d, years):
    """Same calendar date N years later (Feb 29 falls back to Feb 28)."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def parse_iso8601(s):
    """Tolerant parser for the clock endpoint's to_iso8601 input."""
    if not isinstance(s, str) or not s.strip():
        _invalid("Field 'to_iso8601' is required and must be an ISO 8601 timestamp")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        _invalid("Field 'to_iso8601' must be a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --- Money: integer cents, round-half-up on multiplicative results (§2.6) ----
def round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec_rate(s):
    return Decimal(s)


# --- Pagination (§2.3: limit default 10, min 1, max 100; offset default 0) ---
def paginate(entities):
    try:
        limit = int(request.args.get("limit"))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset"))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    ordered = sorted(entities, key=lambda e: (e["created_at"], e["_seq"]))
    return ordered, limit, offset


def due_date_plus_30(today):
    return (today + timedelta(days=30)).isoformat()
