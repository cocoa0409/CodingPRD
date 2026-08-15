"""Time parsing/formatting, request-id generation, scalar validators."""
import secrets
import string
from datetime import datetime, timezone

UTC = timezone.utc

_ALNUM = string.ascii_letters + string.digits


def now_wall():
    return datetime.now(UTC)


def fmt(dt):
    """ISO 8601 UTC at second granularity, e.g. 2026-08-01T00:00:00Z.

    Default rendering for business timestamps (issued_at, closed_at,
    kickoff_at, laundry_due_at, certification_expires_on).
    """
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_ms(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z.

    Used for created_at/updated_at (PRD §2.5) and api_request_timestamp (§2.2),
    which explicitly require three fractional digits.
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


def parse_date(value):
    """Strict YYYY-MM-DD -> datetime.date, else None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if len(s) != 10:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_pct(v):
    """Fraction in [0, 1]; bools excluded."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1


def new_request_id():
    return "req_" + "".join(secrets.choice(_ALNUM) for _ in range(24))
