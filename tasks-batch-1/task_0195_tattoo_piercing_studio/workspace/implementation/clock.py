"""Logical UTC clock (PRD §2.8).

The server maintains a logical UTC clock used for all time-gated decisions:
no-show eligibility, reschedule validity, and the touch-up free-window cutoff.
The test-driving endpoint POST /studio/_clock/set_current_utc can pin it.

Real wall-clock time is used for created_at / updated_at / api_request_timestamp
(server-managed audit fields) — the logical clock only governs business-time
decisions. When the logical clock is set, business-time reads return that value.
"""
from datetime import datetime, timezone

_override = None  # type: datetime | None


def now_dt():
    """Real wall-clock UTC datetime (for created_at / updated_at / request ts)."""
    return datetime.now(timezone.utc)


def _fmt_millis(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso_millis():
    """Wall-clock ISO 8601 UTC with three fractional digits."""
    return _fmt_millis(now_dt())


def logical_now():
    """Business-time logical clock: the override if set, else wall clock."""
    if _override is not None:
        return _override
    return now_dt()


def set_logical_now(dt):
    global _override
    _override = dt


def logical_now_iso_millis():
    return _fmt_millis(logical_now())


def parse_iso8601(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
