"""Time parsing/formatting, request-id generation, scalar validators."""
import re
import secrets
import string
from datetime import datetime, timezone

UTC = timezone.utc

_ALNUM = string.ascii_letters + string.digits


def now_wall():
    return datetime.now(UTC)


def fmt(dt):
    """ISO 8601 UTC at second granularity, e.g. 2026-05-01T00:00:00Z.

    This is the default rendering for all business timestamps (issued_at,
    proposed_at, scheduled_at, filed_at, closed_at, deadlines, etc.). The PRD
    specifies "ISO 8601 UTC" generally; only `created_at` and
    `api_request_timestamp` are explicitly required to carry three fractional
    digits (see `fmt_ms`).
    """
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_ms(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-05-01T00:00:00.000Z.

    Used for `created_at` and `api_request_timestamp`, which the PRD §2.2/§2.5
    explicitly requires to carry three fractional digits.
    """
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_meta_ts():
    return fmt_ms(now_wall())


def parse_dt(value):
    """Parse an ISO 8601 string (Z or offset, date-only allowed) to aware UTC datetime.

    Returns None when the value is not a parseable string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s[-1] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def new_request_id():
    return "req_" + "".join(secrets.choice(_ALNUM) for _ in range(24))


def academic_year_start(dt):
    """Academic year of a date: window [Y-07-01, (Y+1)-06-30] where Y is the
    date's own year when month >= 7, else prior year. Returns Y."""
    return dt.year if dt.month >= 7 else dt.year - 1


def parse_academic_year(value):
    """Parse 'YYYY-YYYY' with second == first + 1. Returns first year or None."""
    if not isinstance(value, str):
        return None
    m = re.fullmatch(r"(\d{4})-(\d{4})", value.strip())
    if not m:
        return None
    y1, y2 = int(m.group(1)), int(m.group(2))
    if y2 != y1 + 1:
        return None
    return y1
