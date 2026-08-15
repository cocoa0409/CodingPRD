"""Envelope, id/timestamp helpers, parsing and money rounding utilities."""

import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify

from store import now, next_seq


# ---------------------------------------------------------------------------
# Ids / timestamps
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.2/§2.6)."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_clock(dt):
    """Clock echo format: plain seconds when whole, else milliseconds."""
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_ts(dt)


def parse_dt(value):
    """Parse an ISO 8601 datetime (Z or offset). Returns aware UTC datetime
    or None when unparseable."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD date. Returns datetime.date or None."""
    if not isinstance(value, str):
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def stamp_now():
    """Timestamp string for created_at/updated_at — logical clock, ms precision."""
    return fmt_ts(now())


def touch(entity):
    """Common-field maintenance on every mutation (incl. system cascades)."""
    entity["version"] = int(entity.get("version", 1)) + 1
    entity["updated_at"] = stamp_now()


def new_entity(fields):
    """Attach the standard common fields to a freshly created entity dict."""
    ts = stamp_now()
    fields.setdefault("id", new_id())
    fields["created_at"] = ts
    fields["updated_at"] = ts
    fields["version"] = 1
    fields["_seq"] = next_seq()
    return fields


def add_months(dt, months):
    """Step-month addition used for training validity (CERT_VALIDITY_MONTHS)."""
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    # clamp day to last day of target month
    if m == 12:
        first_next = datetime(y + 1, 1, 1, tzinfo=dt.tzinfo)
    else:
        first_next = datetime(y, m + 1, 1, tzinfo=dt.tzinfo)
    last_day = (first_next - timedelta(days=1)).day
    d = min(dt.day, last_day)
    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------------------
# Money — integer cents, round-half-up applied exactly once per computation
# ---------------------------------------------------------------------------

def round_half_up_cents(value):
    """Round a Decimal-compatible value half-up to whole cents (int)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money_mul_div(amount_int, mul, div):
    """round_half_up(amount * mul / div) computed in Decimal."""
    d = (Decimal(int(amount_int)) * Decimal(mul)) / Decimal(div)
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_of(amount_int, pct):
    """round_half_up(amount * pct) with pct a 0..1 fraction (int/float/str)."""
    d = Decimal(int(amount_int)) * Decimal(str(pct))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div(a, b):
    return -(-int(a) // int(b))


def whole_minutes(delta):
    """Whole-minute magnitude of a timedelta (floor toward zero for the
    positive durations this domain uses)."""
    return int(delta.total_seconds() // 60)


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD §1.0 verbatim)
# ---------------------------------------------------------------------------

def _meta():
    import secrets
    return {
        "api_request_id": "req_" + secrets.token_hex(8),
        # Request receipt timestamp — wall clock, 3 fractional digits.
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Pagination (limit default 10, clamp 1..100; offset default 0, min 0)
# ---------------------------------------------------------------------------

def parse_pagination(args):
    from errors import fail
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def paginate(items, limit, offset, serializer):
    """items: full filtered list (already sorted). Returns Flask response."""
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serializer(x) for x in page], total, limit, offset)


def sort_default(items):
    """created_at ascending (insertion order breaks same-instant ties)."""
    return sorted(items, key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))
