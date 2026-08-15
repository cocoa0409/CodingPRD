"""Shared helpers: rounding, dates, ISO weeks, structural body validation."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import ERR_INVALID_REQUEST, ApiError

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

SERVICE_LEVELS = {"ONE_TO_ONE", "SHARED_SUPPORT", "TRANSITIONAL"}
QUALIFICATIONS = {"NONE", "BEHAVIOR_SUPPORT", "MEDICAL_DELEGATION", "SIGN_LANGUAGE"}
CHANGE_TYPES = {"MINUTES_CHANGE", "QUALIFICATION_CHANGE", "BUILDING_TRANSFER", "EXIT"}


def new_id():
    return str(uuid.uuid4())


def dec(x):
    """Exact Decimal from an int/float/str JSON number."""
    return Decimal(str(x))


def rhu(x):
    """Round half-up to integer."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def iso_ts(dt):
    """ISO 8601 UTC with three fractional digits (PRD §2.5)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_date(s):
    """Parse YYYY-MM-DD -> date, else None."""
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def parse_dt(s):
    """Parse ISO 8601 timestamp -> aware UTC datetime, else None."""
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


def week_monday(d):
    """Monday (ISO week start) of the week containing date d."""
    return d - timedelta(days=d.weekday())


def bad_request(msg):
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


# ---------------------------------------------------------------------------
# Structural body validation -> ERR_INVALID_REQUEST (400)
# ---------------------------------------------------------------------------

def body_json(req):
    data = req.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad_request("request body must be a JSON object")
    return data


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


def as_date_str(v, field):
    """Valid YYYY-MM-DD string (structural); semantic range checks elsewhere."""
    s = as_str(v, field)
    if parse_date(s) is None:
        bad_request("field %s must be an ISO date (YYYY-MM-DD)" % field)
    return s


def as_enum(v, field, allowed):
    s = as_str(v, field)
    if s not in allowed:
        bad_request("field %s must be one of %s" % (field, sorted(allowed)))
    return s


def as_days_of_week(v):
    if not isinstance(v, list) or not v:
        bad_request("days_of_week must be a non-empty array")
    out = []
    for d in v:
        if not isinstance(d, str) or d not in WEEKDAYS:
            bad_request("days_of_week entries must be weekday codes")
        if d in out:
            bad_request("days_of_week entries must be distinct")
        out.append(d)
    return out
