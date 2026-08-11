"""Shared helpers: serialization, pagination, decimal handling, fiscal calendar."""
import math
import re
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta

import db
from errors import err_invalid_request

H2 = Decimal("0.01")


def dec2(v):
    """Round to 2dp half-up, returned as float for JSON."""
    if v is None:
        return None
    d = Decimal(str(v)).quantize(H2, rounding=ROUND_HALF_UP)
    return float(d)


def round_half_up_int(v):
    """Round a Decimal/number half-up to integer."""
    return int(Decimal(str(v)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money(v):
    return round_half_up_int(v)


def hours_val(v):
    """Quantize hour bucket to 2dp half-up -> float."""
    return float(Decimal(str(v)).quantize(H2, rounding=ROUND_HALF_UP))


# ---------------- request body helpers ----------------
def body():
    from flask import request
    if not request.is_json:
        data = request.get_json(silent=True)
        if data is None:
            return {}
        return data
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise err_invalid_request(f"Field '{field}' is required and must be a string")
    return v


def opt_str(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, str):
        raise err_invalid_request(f"Field '{field}' must be a string")
    return v


def req_int(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"Field '{field}' is required and must be an integer")
    return v


def opt_int(data, field, default=None):
    v = data.get(field, default)
    if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
        raise err_invalid_request(f"Field '{field}' must be an integer")
    return v


def opt_bool(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, bool):
        raise err_invalid_request(f"Field '{field}' must be a boolean")
    return v


def req_number(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request(f"Field '{field}' is required and must be a number")
    return v


def opt_number(data, field, default=None):
    v = data.get(field, default)
    if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
        raise err_invalid_request(f"Field '{field}' must be a number")
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if v not in allowed:
        raise err_invalid_request(f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def req_ts(data, field):
    v = data.get(field)
    if not isinstance(v, str):
        raise err_invalid_request(f"Field '{field}' is required and must be an ISO 8601 timestamp")
    try:
        return db.parse_ts(v)
    except Exception:
        raise err_invalid_request(f"Field '{field}' is not a valid ISO 8601 timestamp")


def valid_hour_quantity(v):
    """Hour quantities: multiple of 0.25 within 1.00..80.00."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    d = Decimal(str(v))
    if d < Decimal("1.00") or d > Decimal("80.00"):
        return False
    q = (d * 4) % 1
    return q == 0


def req_hours(data, field):
    v = data.get(field)
    if not valid_hour_quantity(v):
        raise err_invalid_request(
            f"Field '{field}' must be a multiple of 0.25 within 1.00..80.00"
        )
    return float(v)


# ---------------- pagination ----------------
def paginate(items, response_builder=None):
    """Apply limit/offset; return (page, pagination_meta)."""
    from flask import request
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except ValueError:
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except ValueError:
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    items = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


# ---------------- fiscal calendar ----------------
def quarter_bounds(fiscal_year_start, ref):
    """Return (period_start, period_end) of the fiscal quarter containing ref.
    Quarters are 3-calendar-month blocks anchored to fiscal_year_start (a date)."""
    fy = fiscal_year_start  # a date
    # Normalize ref to date at UTC midnight for comparison.
    ref_date = ref.date() if isinstance(ref, datetime) else ref
    # find k such that fy + 3k months <= ref_date < fy + 3(k+1) months
    k = 0
    start = fy
    while True:
        end = add_months(start, 3)
        if ref_date < end:
            return (
                datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
                datetime(end.year, end.month, end.day, tzinfo=timezone.utc),
            )
        start = end
        k += 1
        if k > 400:
            break
    # fallback (should not happen)
    end = add_months(fy, 3)
    return (
        datetime(fy.year, fy.month, fy.day, tzinfo=timezone.utc),
        datetime(end.year, end.month, end.day, tzinfo=timezone.utc),
    )


def add_months(d, n):
    """Add n calendar months to a date."""
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    # day stays the same; clamp if necessary
    day = d.day
    while True:
        try:
            return d.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


def fiscal_year_bounds(fiscal_year_start, ref):
    """Return (year_start, year_end) of fiscal year containing ref."""
    fy = fiscal_year_start
    ref_date = ref.date() if isinstance(ref, datetime) else ref
    start = fy
    while True:
        end = add_months(start, 12)
        if ref_date < end:
            return start, end
        start = end


# ---------------- overlap ----------------
def overlaps(a_start, a_end, b_start, b_end):
    """Half-open [a_start,a_end) vs [b_start,b_end) overlap test."""
    return a_start < b_end and b_start < a_end


# ---------------- serialization ----------------
def serialize(entity, kind):
    """Convert internal entity to JSON-safe dict per scaffold field names."""
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = db.fmt_ts(v)
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out
