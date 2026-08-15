"""Shared helpers: ids, timestamps, parsing, decimal rounding, entities."""
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from errors import ApiError

HIGH_RISK_COUNTRIES = {"IR", "KP", "CU", "SY"}

TXN_TYPES = {"CASH_DEPOSIT", "WIRE_IN", "WIRE_OUT", "ACH_DEBIT", "CHECK_DEPOSIT"}
DIRECTIONS = {"CREDIT", "DEBIT"}
CHANNELS = {"BRANCH", "ATM", "ONLINE", "WIRE_DESK"}
DIRECTION_FILTERS = {"CREDIT", "DEBIT", "BOTH"}
COUNTRY_RISKS = {"LOW", "HIGH"}
ACCOUNT_DECISIONS = {"EXIT", "RESTRICT", "RETAIN"}
SHARE_DIRECTIONS = {"OUTBOUND", "INBOUND"}
CASE_DECISIONS = {"SAR_REQUIRED", "NO_SAR"}
QA_OUTCOMES = {"PASS", "FAIL"}
REVIEW_OUTCOMES = {"FILE_CONTINUING_SAR", "CLOSE_MONITORING"}


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def iso_z(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now():
    return datetime.now(timezone.utc)


def parse_dt(value):
    """Parse an ISO 8601 datetime into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD date. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if len(text) != 10 or "T" in text:
        raise ValueError("not a date")
    return date.fromisoformat(text)


def dec(value):
    """Decimal from a JSON number (rejects bool/non-numeric)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("not a number")
    return Decimal(str(value))


def round4(d):
    return d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def round0_int(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_int(d):
    return int(d.to_integral_value(rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------

def base_entity():
    import db
    ts = db.now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(entity, bump_version=True):
    import db
    entity["updated_at"] = db.now()
    if bump_version:
        entity["version"] += 1


def serialize(entity):
    out = {}
    for key, value in entity.items():
        if key == "_seq":
            continue
        if isinstance(value, datetime):
            out[key] = iso_z(value)
        elif isinstance(value, date):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


def sort_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


# ---------------------------------------------------------------------------
# Request-body field validators (priority 1: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg, 400)


def req_str(body, key, allow_empty=False):
    v = body.get(key)
    if not isinstance(v, str) or (not allow_empty and v == ""):
        _bad(f"Field '{key}' is required and must be a non-empty string")
    return v


def opt_str(body, key, default=None):
    v = body.get(key, default)
    if v is None:
        return None
    if not isinstance(v, str):
        _bad(f"Field '{key}' must be a string")
    return v


def req_enum(body, key, allowed):
    v = body.get(key)
    if not isinstance(v, str) or v not in allowed:
        _bad(f"Field '{key}' must be one of {sorted(allowed)}")
    return v


def req_int(body, key, minimum=None):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(f"Field '{key}' is required and must be an integer")
    if minimum is not None and v < minimum:
        _bad(f"Field '{key}' must be >= {minimum}")
    return v


def opt_int(body, key, default=None, minimum=None):
    if key not in body or body[key] is None:
        return default
    return req_int(body, key, minimum=minimum)


def req_num(body, key):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(f"Field '{key}' is required and must be a number")
    return v


def opt_num(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    return req_num(body, key)


def req_num_range(body, key, lo, hi):
    v = req_num(body, key)
    if v < lo or v > hi:
        _bad(f"Field '{key}' must be in [{lo}, {hi}]")
    return v


def req_bool(body, key):
    v = body.get(key)
    if not isinstance(v, bool):
        _bad(f"Field '{key}' is required and must be a boolean")
    return v


def opt_bool(body, key, default=False):
    if key not in body or body[key] is None:
        return default
    return req_bool(body, key)


def req_dt(body, key):
    v = body.get(key)
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        _bad(f"Field '{key}' is required and must be an ISO 8601 datetime")


def opt_dt(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    return req_dt(body, key)


def req_date(body, key):
    v = body.get(key)
    try:
        return parse_date(v)
    except (ValueError, TypeError):
        _bad(f"Field '{key}' is required and must be a YYYY-MM-DD date")


def opt_date(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    return req_date(body, key)
