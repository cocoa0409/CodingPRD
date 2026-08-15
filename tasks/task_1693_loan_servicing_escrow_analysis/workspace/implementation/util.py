"""Time, date-math, money, and response-envelope helpers."""

import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

from errors import ApiError, ERR_INVALID_REQUEST
from store import store

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------

ADVANCE_CAP_CENTS = 1000000
SURPLUS_REFUND_THRESHOLD_CENTS = 5000

FEDERAL_HOLIDAYS = {
    "2026-09-07", "2026-10-12", "2026-11-11", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-05-31", "2027-07-05",
    "2027-09-06", "2027-10-11", "2027-11-11", "2027-11-25", "2027-12-24",
    "2027-12-31",
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ----------------------------------------------------------------------------
# Logical clock
# ----------------------------------------------------------------------------

def now_dt():
    return store.clock


def today():
    return store.clock.date()


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_clock(dt):
    """Logical-clock serialization: no fractional part when zero."""
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_ts(dt)


def now_ts():
    return fmt_ts(store.clock)


def fmt_date(d):
    return d.isoformat()


def wallclock_ts():
    return fmt_ts(datetime.now(timezone.utc))

# ----------------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------------

def parse_date(s):
    """Strict ISO YYYY-MM-DD -> date, else None."""
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def parse_dt(s):
    """ISO 8601 datetime (Z or offset) -> aware datetime UTC, else None."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    try:
        if txt.endswith("Z"):
            dt = datetime.fromisoformat(txt[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

# ----------------------------------------------------------------------------
# Date math
# ----------------------------------------------------------------------------

def add_months(d, n):
    """Add n calendar months to date d, clamping the day of month."""
    total = (d.year * 12 + (d.month - 1)) + n
    y, m0 = divmod(total, 12)
    m = m0 + 1
    # days in month
    if m == 12:
        nxt = date(y + 1, 1, 1)
    else:
        nxt = date(y, m + 1, 1)
    dim = (nxt - date(y, m, 1)).days
    return date(y, m, min(d.day, dim))


def days_30360(d1, d2):
    """30/360 US day count: D1 capped at 30; D2=31 -> 30 only when D1 in {30,31}."""
    dd1 = min(d1.day, 30)
    dd2 = d2.day
    if dd2 == 31 and d1.day >= 30:
        dd2 = 30
    return 360 * (d2.year - d1.year) + 30 * (d2.month - d1.month) + (dd2 - dd1)


def add_business_days(start, n):
    """Count forward one calendar day at a time counting only business days;
    the start day itself is day 0 and never counted."""
    d = start
    count = 0
    while count < n:
        d = d + timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in FEDERAL_HOLIDAYS:
            count += 1
    return d

# ----------------------------------------------------------------------------
# Money
# ----------------------------------------------------------------------------

def rhu(value):
    """Round half-up to whole cents; value may be Decimal/int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_div(a, b):
    return rhu(Decimal(a) / Decimal(b))

# ----------------------------------------------------------------------------
# Records
# ----------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def new_record(fields):
    r = dict(fields)
    r["id"] = new_id()
    r["_seq"] = store.next_seq()
    r["created_at"] = now_ts()
    r["updated_at"] = r["created_at"]
    r["version"] = 1
    return r


def new_ledger_entry(fields):
    """Ledger entries are immutable: id + created_at only."""
    r = dict(fields)
    r["id"] = new_id()
    r["_seq"] = store.next_seq()
    r["created_at"] = now_ts()
    return r


def bump(rec):
    rec["version"] += 1
    rec["updated_at"] = now_ts()


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}

# ----------------------------------------------------------------------------
# Response envelope (per SCAFFOLD response_envelope)
# ----------------------------------------------------------------------------

def _rid():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def ok(data, status=200):
    body = {
        "meta": {
            "api_request_id": _rid(),
            "api_request_timestamp": wallclock_ts(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def _parse_pagination():
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    limit, offset = 10, 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def ok_list(items):
    limit, offset = _parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    body = {
        "meta": {
            "api_request_id": _rid(),
            "api_request_timestamp": wallclock_ts(),
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + len(page)) < total,
        },
        "response_type": "array",
        "data": page,
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": {
            "api_request_id": _rid(),
            "api_request_timestamp": wallclock_ts(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
