"""Shared helpers: datetimes, decimals, record bookkeeping, pagination, and
request-shape validation."""

import calendar
from datetime import datetime, timedelta, timezone
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from flask import request

from db import STORES, new_id, next_seq, now
from errors import ApiError

# ---------------------------------------------------------------------------
# Datetimes
# ---------------------------------------------------------------------------


def parse_dt(value):
    """Parse an ISO 8601 string into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits (system-stamped fields)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_clock(dt):
    """Clock echo format: matches the startup default style (no fractional
    digits when the value lands on a whole second)."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_ts(dt)


def add_months(dt, months):
    """Add calendar months, clamping the day to the target month's length."""
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------------------
# Decimals (money is integer cents; usage quantities are 4dp half-up)
# ---------------------------------------------------------------------------


def dec(value):
    return Decimal(str(value))


def round0(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round4(d):
    return d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def ceil_dec(d):
    return int(d.to_integral_value(rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# Record bookkeeping
# ---------------------------------------------------------------------------


def base_record():
    t = now()
    return {
        "id": new_id(),
        "created_at": fmt_ts(t),
        "updated_at": fmt_ts(t),
        "version": 1,
        "_created_dt": t,
        "_updated_dt": t,
        "_seq": next_seq(),
    }


def touch(rec):
    t = now()
    rec["updated_at"] = fmt_ts(t)
    rec["_updated_dt"] = t
    rec["version"] += 1


def pub(rec):
    """Public view of a record: strip internal underscore-prefixed keys."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sorted_default(recs):
    """created_at ASC, tie-break updated_at ASC, then insertion order."""
    return sorted(recs, key=lambda r: (r["_created_dt"], r["_updated_dt"], r["_seq"]))


def get_or_404(store, rid):
    rec = STORES[store].get(rid)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Resource not found: " + str(rid))
    return rec


def fk_exists(data, field, store):
    """Rung-3 existence check for a body foreign key, when extractable."""
    value = data.get(field)
    if isinstance(value, str) and value != "":
        if value not in STORES[store]:
            raise ApiError(
                "ERR_RESOURCE_NOT_FOUND",
                404,
                f"{field} does not reference an existing resource",
            )


# ---------------------------------------------------------------------------
# Request body + shape validation (rung 4)
# ---------------------------------------------------------------------------


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _bad(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", 400, f"Invalid field {field}: {detail}")


def v_str(data, field, required=True, default=None):
    v = data.get(field)
    if v is None:
        if required:
            _bad(field, "required string missing")
        return default
    if not isinstance(v, str):
        _bad(field, "must be a string")
    return v


def v_int(data, field, required=True, default=None, min_val=None):
    v = data.get(field)
    if v is None:
        if required:
            _bad(field, "required integer missing")
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(field, "must be an integer")
    if min_val is not None and v < min_val:
        _bad(field, f"must be >= {min_val}")
    return v


def v_num(data, field, required=True, default=None):
    v = data.get(field)
    if v is None:
        if required:
            _bad(field, "required number missing")
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(field, "must be a number")
    return v


def v_bool(data, field, required=True, default=None):
    v = data.get(field)
    if v is None:
        if required:
            _bad(field, "required boolean missing")
        return default
    if not isinstance(v, bool):
        _bad(field, "must be a boolean")
    return v


def v_enum(data, field, members, required=True, default=None):
    v = data.get(field)
    if v is None:
        if required:
            _bad(field, "required enum missing")
        return default
    if v not in members:
        _bad(field, f"must be one of {sorted(members)}")
    return v


def v_dt(data, field, required=True, default=None):
    """Returns (raw_string, parsed_datetime). Raises 400 when malformed."""
    v = data.get(field)
    if v is None:
        if required:
            _bad(field, "required datetime missing")
        return default
    parsed = parse_dt(v)
    if parsed is None:
        _bad(field, "malformed datetime")
    return v, parsed


def v_list(data, field, required=True, default=None):
    v = data.get(field)
    if v is None:
        if required:
            _bad(field, "required array missing")
        return default
    if not isinstance(v, list):
        _bad(field, "must be an array")
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3)
# ---------------------------------------------------------------------------


def paginate(recs):
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    # limit accepts a minimum of 1 and is capped at a maximum of 100
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(recs)
    page = recs[offset : offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, pagination
