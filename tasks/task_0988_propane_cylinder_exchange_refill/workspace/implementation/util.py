"""Shared parsing / validation / numeric helpers."""
import math
from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import request

import db
from errors import ApiError, ERR_VALIDATION


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "Request body must be a JSON object")
    return data


def _fail(msg):
    raise ApiError(ERR_VALIDATION, 400, msg)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(b, name):
    v = b.get(name)
    if v is None or not isinstance(v, str) or v == "":
        _fail("Missing or invalid required field: %s" % name)
    return v


def opt_str(b, name, default=None):
    v = b.get(name, default)
    if v is None:
        return None
    if not isinstance(v, str):
        _fail("Invalid field: %s" % name)
    return v


def req_int(b, name, min_v=None, max_v=None):
    v = b.get(name)
    if not is_int(v):
        _fail("Missing or invalid required integer field: %s" % name)
    if min_v is not None and v < min_v:
        _fail("Field %s below minimum %s" % (name, min_v))
    if max_v is not None and v > max_v:
        _fail("Field %s above maximum %s" % (name, max_v))
    return v


def opt_int(b, name, default=None, min_v=None, max_v=None):
    if name not in b or b[name] is None:
        return default
    return req_int(b, name, min_v=min_v, max_v=max_v)


def req_num(b, name):
    """Parse a JSON number into Decimal (exact via str)."""
    v = b.get(name)
    if isinstance(v, bool) or v is None or not isinstance(v, (int, float)):
        _fail("Missing or invalid required numeric field: %s" % name)
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        _fail("Invalid numeric field: %s" % name)
    if not d.is_finite():
        _fail("Invalid numeric field: %s" % name)
    return d


def opt_num(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    return req_num(b, name)


def req_bool(b, name):
    v = b.get(name)
    if not isinstance(v, bool):
        _fail("Missing or invalid required boolean field: %s" % name)
    return v


def opt_bool(b, name, default=False):
    if name not in b or b[name] is None:
        return default
    return req_bool(b, name)


_DATE_ERR = "Invalid ISO calendar date"


def parse_date_str(v, name="date"):
    if not isinstance(v, str):
        _fail("%s: %s" % (_DATE_ERR, name))
    try:
        d = datetime.strptime(v, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        _fail("%s: %s" % (_DATE_ERR, name))
    # strptime is lenient about some forms; enforce exact round-trip.
    if d.isoformat() != v:
        _fail("%s: %s" % (_DATE_ERR, name))
    return v


def req_date(b, name):
    if name not in b or b[name] is None:
        _fail("Missing required field: %s" % name)
    return parse_date_str(b[name], name)


def opt_date(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    return parse_date_str(b[name], name)


def req_enum(b, name, values):
    v = b.get(name)
    if v not in values:
        _fail("Missing or invalid enum field: %s" % name)
    return v


def opt_enum(b, name, values, default=None):
    if name not in b or b[name] is None:
        return default
    return req_enum(b, name, values)


def parse_instant(s):
    """Parse an ISO 8601 instant (accepts trailing Z or offset; date-only -> midnight UTC)."""
    if not isinstance(s, str) or not s:
        _fail("Invalid to_iso8601 instant")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        _fail("Invalid to_iso8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_instant(dt):
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += "." + f"{dt.microsecond // 1000:03d}"
    return base + "Z"


def add_years(date_str, years):
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    try:
        nd = d.replace(year=d.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 on non-leap target years.
        nd = d.replace(year=d.year + years, day=28)
    return nd.isoformat()


def q2(d):
    """Round a Decimal half-up to two decimal places (weights)."""
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_cents(dec):
    """Round a Decimal half-up to whole cents, returned as int."""
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def bps_amount(cents, bps):
    """Apply a basis-point rate to a cent amount (Decimal math, unrounded)."""
    return Decimal(cents) * Decimal(bps) / Decimal(10000)


def ceil_div(a, b):
    return -(-a // b)


def paginate(items):
    """Parse limit/offset query params (defaults 10 / 0; limit in 1..100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _fail("Invalid limit")
        if str(raw_limit).strip() != str(limit):
            _fail("Invalid limit")
        if limit < 1 or limit > 100:
            _fail("limit out of range (1..100)")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _fail("Invalid offset")
        if str(raw_offset).strip() != str(offset):
            _fail("Invalid offset")
        if offset < 0:
            _fail("offset out of range (>= 0)")
    total = len(items)
    return items[offset:offset + limit], total, limit, offset


def sorted_by_creation(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_created_seq"]))
