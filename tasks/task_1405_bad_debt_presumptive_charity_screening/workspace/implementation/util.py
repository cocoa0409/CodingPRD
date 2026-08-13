"""Shared helpers: logical clock, ISO formatting, date math, money rounding,
request-body shape validation, pagination, record helpers."""

import json
import uuid
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


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2/2.5),
    e.g. 2026-08-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_sec(dt):
    """ISO 8601 UTC at whole-second precision, e.g. 2026-08-01T00:00:00Z.
    Used for the clock-advance echo (now_iso8601)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso():
    return iso_ms(db.now)


def parse_datetime_value(s):
    """Parse an ISO 8601 datetime (accepts trailing Z and date-only) -> aware UTC."""
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


def parse_dt(s):
    """Parse a stored ISO timestamp back to an aware UTC datetime."""
    return parse_datetime_value(s)


def parse_date_value(s):
    """Validate an ISO YYYY-MM-DD date; returns (date_obj, canonical_string)."""
    if not isinstance(s, str):
        raise ApiError(ERR_INVALID_REQUEST, "invalid date value", 400)
    try:
        d = date.fromisoformat(s.strip())
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, "invalid date value: %r" % s, 400)
    return d, d.isoformat()


def day_start(dt_date):
    return datetime.combine(dt_date, time(0, 0, 0), tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# money rounding (PRD 2.6): contingency fees round half up; recall fee and
# vendor rate / fpl percent round down. All money is integer cents.
# ---------------------------------------------------------------------------

def fee_round_half_up(amount_cents, bps):
    """round_half_up(amount_cents * bps / 10000) to a whole cent."""
    return int((Decimal(amount_cents) * Decimal(bps) / Decimal(10000)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


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


def req_enum(b, k, values):
    v = req_str(b, k)
    if v not in values:
        raise ApiError(ERR_INVALID_REQUEST,
                       "field %s must be one of %s" % (k, sorted(values)), 400)
    return v


def req_date(b, k):
    """Required ISO date field; returns canonical YYYY-MM-DD string."""
    _, canonical = parse_date_value(req_str(b, k))
    return canonical


# ---------------------------------------------------------------------------
# pagination (PRD 2.3): limit default 10 (min 1, max 100), offset default 0;
# lists sorted by creation timestamp ascending (insertion order as tiebreak)
# ---------------------------------------------------------------------------

def _pag_int(raw, default, name):
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST,
                       "query parameter %s must be an integer" % name, 400)


def paginate(items):
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
    """Every mutation refreshes updated_at and increments version by exactly 1
    (PRD 2.5) — including mutations caused by cascading side effects."""
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


def append_only_record():
    """MedicareBadDebtLogEntry / VendorPerformanceSnapshot carry only id and
    created_at from the standard set (PRD 2.5) — no updated_at, no version."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": db.next_seq(),
    }


def serialize(rec, extra=None):
    out = {k: v for k, v in rec.items() if not k.startswith("_")}
    if extra:
        out.update(extra)
    return out
