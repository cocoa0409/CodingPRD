"""Shared helpers: logical clock, ISO formatting, dates, business days,
rounding, request-body shape validation, pagination."""

import json
import uuid
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import db
from errors import ApiError, ERR_INVALID_REQUEST


# ---------------------------------------------------------------------------
# logical clock / timestamps
# ---------------------------------------------------------------------------

def now_dt():
    return db.now


def today():
    return db.now.date()


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(db.now)


def parse_datetime_value(s):
    """Parse an ISO 8601 datetime (accepts trailing Z and date-only). -> aware UTC datetime."""
    if not isinstance(s, str):
        raise ApiError(ERR_INVALID_REQUEST, "invalid datetime value", 400)
    t = s.strip()
    try:
        if len(t) == 10:
            d = date.fromisoformat(t)
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, "invalid datetime value: %r" % s, 400)


def parse_date_value(s):
    """Validate an ISO YYYY-MM-DD date; returns (date_obj, canonical_string)."""
    if not isinstance(s, str):
        raise ApiError(ERR_INVALID_REQUEST, "invalid date value", 400)
    try:
        d = date.fromisoformat(s.strip())
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, "invalid date value: %r" % s, 400)
    return d, d.isoformat()


# ---------------------------------------------------------------------------
# business days / calendar math
# ---------------------------------------------------------------------------

def business_days_between(a, b):
    """Count of weekday dates d in the half-open interval (a, b] (PRD 2.4)."""
    if b <= a:
        return 0
    count = 0
    d = a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return count


def add_business_days(a, n):
    d = a
    added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


def add_calendar_month(d):
    """One calendar month after d, day clamped to the target month's end."""
    y, m = d.year, d.month + 1
    if m > 12:
        y += 1
        m = 1
    last = monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


def end_of_day_iso(d):
    return iso(datetime.combine(d, time(23, 59, 59, 999000), tzinfo=timezone.utc))


# ---------------------------------------------------------------------------
# money rounding: round half up to whole cents, applied exactly where named
# ---------------------------------------------------------------------------

def rhu(numer, denom=100):
    """round_half_up(numer / denom) to a whole cent (integer result)."""
    return int((Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_rhu_2dp(numer, denom):
    """round_half_up to 2 decimal places -> float (variance_pct only)."""
    q = (Decimal(numer) / Decimal(denom)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return q


# ---------------------------------------------------------------------------
# request body shape validation (priority-4 checks -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def get_body():
    raw = request.get_data(cache=True)
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, "request body must be valid JSON", 400)
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "request body must be a JSON object", 400)
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _missing(b, k):
    return k not in b or b[k] is None


def req_str(b, k):
    if _missing(b, k) or not isinstance(b[k], str):
        raise ApiError(ERR_INVALID_REQUEST, "field %s must be a string" % k, 400)
    return b[k]


def opt_str(b, k, default=None):
    if _missing(b, k):
        return default
    if not isinstance(b[k], str):
        raise ApiError(ERR_INVALID_REQUEST, "field %s must be a string" % k, 400)
    return b[k]


def req_int(b, k):
    if _missing(b, k) or not _is_int(b[k]):
        raise ApiError(ERR_INVALID_REQUEST, "field %s must be an integer" % k, 400)
    return b[k]


def opt_int(b, k, default=None):
    if _missing(b, k):
        return default
    if not _is_int(b[k]):
        raise ApiError(ERR_INVALID_REQUEST, "field %s must be an integer" % k, 400)
    return b[k]


def req_bool(b, k):
    if _missing(b, k) or not isinstance(b[k], bool):
        raise ApiError(ERR_INVALID_REQUEST, "field %s must be a boolean" % k, 400)
    return b[k]


def req_enum(b, k, values):
    v = req_str(b, k)
    if v not in values:
        raise ApiError(ERR_INVALID_REQUEST, "field %s must be one of %s" % (k, sorted(values)), 400)
    return v


def req_date(b, k):
    """Required ISO date field; returns canonical YYYY-MM-DD string."""
    _, canonical = parse_date_value(req_str(b, k))
    return canonical


def opt_date(b, k, default=None):
    if _missing(b, k):
        return default
    _, canonical = parse_date_value(b[k])
    return canonical


# ---------------------------------------------------------------------------
# pagination (PRD 2.3): limit default 10 (min 1, max 100), offset default 0
# ---------------------------------------------------------------------------

def _pag_int(raw, default, name):
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "query parameter %s must be an integer" % name, 400)


def paginate(items):
    """Sort by created_at ascending (insertion order as tiebreak) and paginate."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    limit = _pag_int(request.args.get("limit"), 10, "limit")
    offset = _pag_int(request.args.get("offset"), 0, "offset")
    if limit < 1:
        raise ApiError(ERR_INVALID_REQUEST, "limit must be at least 1", 400)
    if limit > 100:
        limit = 100
    if offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, "offset must be at least 0", 400)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


# ---------------------------------------------------------------------------
# record helpers
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def touch(rec):
    """Every mutation refreshes updated_at and increments version by exactly 1."""
    rec["version"] += 1
    rec["updated_at"] = now_iso()


def base_record():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def serialize(rec, extra=None):
    out = {k: v for k, v in rec.items() if not k.startswith("_")}
    if extra:
        out.update(extra)
    return out
