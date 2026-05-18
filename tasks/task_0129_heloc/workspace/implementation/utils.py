"""Shared utilities: ids, timestamps, time math, rounding."""
from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


# ── ID helpers ──────────────────────────────────────────────────────────────


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


# ── Timestamp formatting (PRD §2.4: ISO 8601 UTC w/ 3 fractional digits) ───


def iso_now(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        raise ValueError(f"Expected datetime string, got {type(value).__name__}")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO datetime: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ── Math helpers ────────────────────────────────────────────────────────────


def round_half_up(value: Decimal) -> int:
    """Round a Decimal value half-up to the nearest whole integer."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def whole_days_between(later: datetime, earlier: datetime) -> int:
    """Whole-day count of (later - earlier).

    PRD §3.9: "The tenure of the account is the whole-day difference
    between closed_at and origination_date."  We floor the seconds-
    difference to integer days so that an account that closes at
    exactly origination_date + 1095 days has tenure of 1095 days (not
    in the early-closure window, per the strict `< 1095` test).
    """
    diff = later - earlier
    return int(diff.total_seconds() // 86400)


def ceil_div(numerator: int, denominator: int) -> int:
    if denominator == 0:
        raise ZeroDivisionError("denominator is zero")
    q, r = divmod(numerator, denominator)
    if r != 0 and ((numerator > 0) == (denominator > 0)):
        q += 1
    return q
