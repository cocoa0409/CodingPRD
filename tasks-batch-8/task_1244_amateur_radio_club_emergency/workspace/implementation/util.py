"""Shared helpers: ids, timestamps, Decimal rounding, structural body validation."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import ERR_VALIDATION, ApiError

LICENSE_ORDER = {"TECHNICIAN": 0, "GENERAL": 1, "EXTRA": 2}
LICENSE_CLASSES = set(LICENSE_ORDER)
BANDS = {"B160M", "B80M", "B40M", "B20M", "B15M", "B10M", "B6M", "B2M"}
MODES = {"CW", "PHONE", "DIGITAL"}
POWER_CATEGORIES = {"QRP", "LOW", "HIGH"}
PRECEDENCES = {"ROUTINE", "PRIORITY", "EMERGENCY"}
RETURN_CONDITIONS = {"GOOD", "DAMAGED"}


def new_id():
    return str(uuid.uuid4())


def dec(x):
    """Exact Decimal from an int/float/str JSON number."""
    return Decimal(str(x))


def rhu(x):
    """Round half-up to integer."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def iso_ts(dt):
    """ISO 8601 UTC with three fractional digits (PRD §2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(s):
    """Parse an ISO 8601 timestamp -> aware UTC datetime, else None."""
    if not isinstance(s, str):
        return None
    try:
        t = s.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        d = datetime.fromisoformat(t)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def bad_request(msg):
    raise ApiError(ERR_VALIDATION, 400, msg)


# ---------------------------------------------------------------------------
# Structural body validation -> ERR_VALIDATION (400), PRD §2.10
# ---------------------------------------------------------------------------

def body_json(req):
    data = req.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad_request("request body must be a JSON object")
    return data


def reject_unknown_fields(body, allowed):
    """Unknown or read-only input fields are rejected (PRD §2.10)."""
    for key in body:
        if key not in allowed:
            bad_request("unknown or read-only field: %s" % key)


def need(body, name):
    if name not in body or body[name] is None:
        bad_request("missing required field: %s" % name)
    return body[name]


def opt(body, name, default=None):
    v = body.get(name, None)
    return default if v is None else v


def as_str(v, field):
    if not isinstance(v, str):
        bad_request("field %s must be a string" % field)
    return v


def as_int(v, field):
    if isinstance(v, bool) or not isinstance(v, int):
        bad_request("field %s must be an integer" % field)
    return v


def as_num(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad_request("field %s must be a number" % field)
    return v


def as_bool(v, field):
    if not isinstance(v, bool):
        bad_request("field %s must be a boolean" % field)
    return v


def as_enum(v, field, allowed):
    s = as_str(v, field)
    if s not in allowed:
        bad_request("field %s must be one of %s" % (field, sorted(allowed)))
    return s


def as_dt(v, field):
    """Valid ISO 8601 datetime string -> aware UTC datetime (else 400)."""
    s = as_str(v, field)
    d = parse_dt(s)
    if d is None:
        bad_request("field %s must be an ISO 8601 timestamp" % field)
    return d
