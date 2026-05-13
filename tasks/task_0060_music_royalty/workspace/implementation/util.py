"""Common utilities: parsing, validation, money math."""

import re
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from errors import raise_err


def round_half_up_cents(amount) -> int:
    """Round a numeric amount (cents, possibly fractional) to integer cents using ROUND_HALF_UP."""
    d = Decimal(str(amount))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_iso8601(s: str) -> datetime:
    """Parse an ISO 8601 datetime string with optional 'Z' suffix. Returns timezone-aware UTC."""
    if not isinstance(s, str):
        raise_err("ERR_VALIDATION", "Invalid timestamp")
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except Exception:
        raise_err("ERR_VALIDATION", "Invalid ISO 8601 timestamp")
        return None  # unreachable
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def parse_iso_date(s: str) -> date:
    if not isinstance(s, str):
        raise_err("ERR_VALIDATION", "Invalid date")
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        raise_err("ERR_VALIDATION", "Invalid YYYY-MM-DD date")


def require_field(body: dict, key: str):
    if key not in body or body[key] is None:
        raise_err("ERR_VALIDATION", f"Missing field: {key}")
    return body[key]


def get_str(body: dict, key: str, min_len: int = 1, max_len: int = 1_000_000, required: bool = True):
    if key not in body or body[key] is None:
        if required:
            raise_err("ERR_VALIDATION", f"Missing field: {key}")
        return None
    v = body[key]
    if not isinstance(v, str):
        raise_err("ERR_VALIDATION", f"Field {key} must be a string")
    if not (min_len <= len(v) <= max_len):
        raise_err("ERR_VALIDATION", f"Field {key} length out of range")
    return v


def get_int(body: dict, key: str, lo=None, hi=None, required: bool = True):
    if key not in body or body[key] is None:
        if required:
            raise_err("ERR_VALIDATION", f"Missing field: {key}")
        return None
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err("ERR_VALIDATION", f"Field {key} must be an integer")
    if lo is not None and v < lo:
        raise_err("ERR_VALIDATION", f"Field {key} below minimum")
    if hi is not None and v > hi:
        raise_err("ERR_VALIDATION", f"Field {key} above maximum")
    return v


def get_number(body: dict, key: str, lo=None, hi=None, required: bool = True):
    if key not in body or body[key] is None:
        if required:
            raise_err("ERR_VALIDATION", f"Missing field: {key}")
        return None
    v = body[key]
    if isinstance(v, bool):
        raise_err("ERR_VALIDATION", f"Field {key} must be numeric")
    if not isinstance(v, (int, float)):
        raise_err("ERR_VALIDATION", f"Field {key} must be numeric")
    if lo is not None and v < lo:
        raise_err("ERR_VALIDATION", f"Field {key} below minimum")
    if hi is not None and v > hi:
        raise_err("ERR_VALIDATION", f"Field {key} above maximum")
    return v


def get_enum(body: dict, key: str, allowed, required: bool = True):
    if key not in body or body[key] is None:
        if required:
            raise_err("ERR_VALIDATION", f"Missing field: {key}")
        return None
    v = body[key]
    if v not in allowed:
        raise_err("ERR_VALIDATION", f"Field {key} not in {allowed}")
    return v


def parse_int_query(value, default, lo=None, hi=None):
    if value is None:
        return default
    try:
        v = int(value)
    except (ValueError, TypeError):
        raise_err("ERR_VALIDATION", "Invalid query int")
        return None
    if lo is not None and v < lo:
        raise_err("ERR_VALIDATION", "Query int below min")
    if hi is not None and v > hi:
        raise_err("ERR_VALIDATION", "Query int above max")
    return v


def parse_pagination(args):
    limit = parse_int_query(args.get("limit"), 10, lo=1, hi=100)
    offset = parse_int_query(args.get("offset"), 0, lo=0)
    return limit, offset


ISRC_RE = re.compile(r"^[A-Z0-9]{12}$")
ISWC_RE = re.compile(r"^T\d{10}$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
URL_RE = re.compile(r"^https?://", re.IGNORECASE)
