"""Shared helpers: common fields, timestamps, rounding, parsing, validation.

Monetary precision (PRD §2.6): integer cents, round_half_up. Therms round half
up to one decimal. Never use float for money rounding decisions — use Decimal.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import store, new_id
from errors import ApiError, ERR_INVALID_REQUEST, err
from response import now_iso


# ---------------------------------------------------------------------------
# Rounding (PRD §2.6)
# ---------------------------------------------------------------------------
def round_half_up_int(value):
    """Round a numeric value half-up to the nearest integer (cents)."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_therms(value):
    """Round to one decimal place, half-up (therms)."""
    d = Decimal(str(value))
    q = d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(q)


# ---------------------------------------------------------------------------
# Common fields (PRD §2.4)
# ---------------------------------------------------------------------------
def attach_common_fields(rec):
    """Add id, created_at, updated_at, version=1 plus an internal _seq."""
    rec["id"] = new_id()
    ts = now_iso()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = store.next_seq()
    return rec


def attach_event_fields(rec):
    """Append-only records (MeterRead, Payment): only id + created_at."""
    rec["id"] = new_id()
    rec["created_at"] = now_iso()
    rec["_seq"] = store.next_seq()
    return rec


def bump(rec):
    """Increment version and refresh updated_at on a mutation (PRD §2.4)."""
    rec["version"] += 1
    rec["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Serialization — strip internal fields
# ---------------------------------------------------------------------------
def public(rec):
    """Return a copy of a record without internal (underscore-prefixed) keys."""
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Body / field validation (PRD §2.10 priority 4 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def get_body():
    from flask import request

    if request.data and len(request.data) > 0:
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            body = None
        if body is None:
            raise err(ERR_INVALID_REQUEST, "Request body is not valid JSON")
        if not isinstance(body, dict):
            raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
        return body
    return {}


def require_fields(body, names):
    for name in names:
        if name not in body or body[name] is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}")


def require_string(body, name):
    val = body.get(name)
    if not isinstance(val, str) or val == "":
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return val


def require_int(body, name, minimum=None, exclusive_min=None):
    val = body.get(name)
    # bool is a subclass of int; reject it explicitly.
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    if exclusive_min is not None and val <= exclusive_min:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be > {exclusive_min}")
    return val


def optional_int(body, name, minimum=None):
    if name not in body or body[name] is None:
        return None
    return require_int(body, name, minimum=minimum)


def require_number(body, name, minimum=None):
    val = body.get(name)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a number")
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    return val


def optional_number(body, name, minimum=None):
    if name not in body or body[name] is None:
        return None
    return require_number(body, name, minimum=minimum)


def require_enum(body, name, choices):
    val = body.get(name)
    if not isinstance(val, str) or val not in choices:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(choices)}")
    return val


def optional_enum(body, name, choices, default=None):
    if name not in body or body[name] is None:
        return default
    return require_enum(body, name, choices)


def optional_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return val


def require_month(body, name):
    """YYYY-MM string."""
    val = body.get(name)
    if not isinstance(val, str):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a YYYY-MM string")
    parts = val.split("-")
    if len(parts) != 2:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be YYYY-MM")
    y, m = parts
    if not (y.isdigit() and m.isdigit() and len(y) == 4 and len(m) == 2):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be YYYY-MM")
    mi = int(m)
    if mi < 1 or mi > 12:
        raise err(ERR_INVALID_REQUEST, f"Field {name} month out of range")
    return val


# ---------------------------------------------------------------------------
# Datetime parsing / comparison
# ---------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO 8601 datetime (or date) string to an aware UTC datetime.

    Accepts trailing 'Z'. Date-only strings are treated as midnight UTC.
    Raises ERR_INVALID_REQUEST on malformed input.
    """
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, "Invalid datetime value")
    s = value.strip()
    txt = s
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        # Try date-only form.
        try:
            dt = datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            raise err(ERR_INVALID_REQUEST, "Invalid datetime value")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    """Current logical clock datetime (aware UTC)."""
    return parse_dt(store.clock["current_utc"])


def to_iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_days_iso(dt, days):
    return to_iso(dt + timedelta(days=days))


# ---------------------------------------------------------------------------
# Sorting / pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def sorted_by_created(records):
    return sorted(records, key=lambda r: r["_seq"])


def parse_pagination():
    from flask import request

    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(records):
    """Sort by created_at ASC, apply limit/offset, return (page, list_meta)."""
    limit, offset = parse_pagination()
    ordered = sorted_by_created(records)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = (offset + limit) < total
    list_meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, list_meta
