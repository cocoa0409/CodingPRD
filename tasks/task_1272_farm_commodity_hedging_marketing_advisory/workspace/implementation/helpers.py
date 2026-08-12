"""Shared helpers: decimal precision, validation, pagination, entity serialization."""

import math
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from flask import request
from errors import ApiError
import db


# ---------- Decimal helpers ----------

def D(x):
    """Coerce to Decimal without float artifacts."""
    if x is None:
        return None
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        return Decimal(str(x))
    return Decimal(str(x))


def r2(x):
    """Round to 2dp half-up."""
    return D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def r3(x):
    """Round to 3dp half-up."""
    return D(x).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def r4(x):
    """Round to 4dp half-up."""
    return D(x).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def to_float(dec):
    """Serialize a Decimal as float (JSON). Keeps clean values like 5.20 as 5.2."""
    if dec is None:
        return None
    return float(dec)


# ---------- Date helpers ----------

def parse_date(s):
    """Parse ISO date string YYYY-MM-DD -> date."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", f"Invalid ISO date: {s!r}", 400)


def parse_iso8601(s):
    """Parse ISO 8601 datetime with optional Z / offset -> aware datetime."""
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", "to_iso8601 must be a string", 400)
    txt = s
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise ApiError("ERR_VALIDATION", f"Invalid ISO8601: {s!r}", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------- Validation helpers ----------

def req_body():
    if not request.is_json:
        raise ApiError("ERR_VALIDATION", "Request body must be JSON", 400)
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object", 400)
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_VALIDATION", f"Missing required field: {f}", 400)


def req_string(body, name):
    v = body.get(name)
    if not isinstance(v, str) or not v:
        raise ApiError("ERR_VALIDATION", f"Field {name} must be a non-empty string", 400)
    return v


def opt_string(body, name, default=None):
    v = body.get(name)
    if v is None:
        return default
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be a string", 400)
    return v


def req_enum(body, name, allowed):
    v = body.get(name)
    if v not in allowed:
        raise ApiError(
            "ERR_VALIDATION",
            f"Field {name} must be one of {sorted(allowed)}",
            400,
        )
    return v


def opt_enum(body, name, allowed, default=None):
    v = body.get(name)
    if v is None:
        return default
    if v not in allowed:
        raise ApiError(
            "ERR_VALIDATION",
            f"Field {name} must be one of {sorted(allowed)}",
            400,
        )
    return v


def req_int(body, name, minimum=None, positive=False):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be an integer", 400)
    if positive and v <= 0:
        raise ApiError("ERR_VALIDATION", f"Field {name} must be > 0", 400)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", f"Field {name} must be >= {minimum}", 400)
    return v


def req_number(body, name, positive=False, minimum=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be a number", 400)
    d = D(v)
    if positive and d <= 0:
        raise ApiError("ERR_VALIDATION", f"Field {name} must be > 0", 400)
    if minimum is not None and d < D(minimum):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be >= {minimum}", 400)
    return d


def opt_number(body, name):
    v = body.get(name)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be a number", 400)
    return D(v)


def check_contract_month(s, field="contract_month"):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", f"{field} must be a string", 400)
    try:
        datetime.strptime(s, "%Y-%m")
    except ValueError:
        raise ApiError("ERR_VALIDATION", f"{field} must be in YYYY-MM form", 400)
    return s


# ---------- Pagination ----------

def pagination_params():
    """limit (default 10, min 1, max 100), offset (default 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except ValueError:
        raise ApiError("ERR_VALIDATION", "limit must be an integer", 400)
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except ValueError:
        raise ApiError("ERR_VALIDATION", "offset must be an integer", 400)
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100", 400)
    if offset < 0:
        raise ApiError("ERR_VALIDATION", "offset must be >= 0", 400)
    return limit, offset


def page_slice(items, limit, offset):
    total = len(items)
    return items[offset : offset + limit], total


# ---------- Entity helpers ----------

def touch(entity):
    """Refresh updated_at and bump version per PRD 2.4 (default mutation semantics)."""
    entity["updated_at"] = db.now_iso()
    entity["version"] = entity.get("version", 0) + 1


def touch_no_version(entity):
    """Refresh updated_at only — for AdvisoryAgreement transitions that per PRD 3.10
    do NOT increment version (deliver-disclosure, acknowledge-disclosure, sign,
    certify-compliance)."""
    entity["updated_at"] = db.now_iso()


def get_or_404(store, key, label="Resource"):
    obj = store.get(key)
    if obj is None:
        raise ApiError("ERR_NOT_FOUND", f"{label} not found: {key}", 404)
    return obj


def latest_settlement_tick(commodity, contract_month=None):
    """Latest SETTLEMENT tick for commodity (+optional contract_month).
    Selection: greatest price_date, tie-break created_at ASC (earliest created wins ties)."""
    best = None
    for t in db.DB.market_ticks.values():
        if t["kind"] != "SETTLEMENT":
            continue
        if t["commodity"] != commodity:
            continue
        if contract_month is not None and t["contract_month"] != contract_month:
            continue
        if best is None:
            best = t
            continue
        if t["price_date"] > best["price_date"]:
            best = t
        elif t["price_date"] == best["price_date"] and t["created_at"] < best["created_at"]:
            best = t
    return best


def month_key_of_date(d):
    """date -> (year, month) tuple."""
    return (d.year, d.month)


def month_bounds(year, month):
    """Return (first_day, last_day) of the month as date objects."""
    first = date(year, month, 1)
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    from datetime import timedelta

    last = nxt - timedelta(days=1)
    return first, last
