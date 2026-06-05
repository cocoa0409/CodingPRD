"""Authoritative server clock (PRD §2.11 / SystemClock entity).

Several rules depend on "now": license & appointment validity, the renewal
window, cancellation / reinstatement timing, and statement-period closure. The
system reads now from this clock rather than wall-clock time. An AgencyAdmin can
pin it via POST /_clock/set_current_utc (to_iso8601). Until set, it defaults to
real wall-clock time.

The clock value is a timezone-aware datetime (UTC). It is process-local and
resets to "unset" (wall clock) on every boot.
"""
from datetime import datetime, timezone

_current_utc = None  # None => fall back to real wall clock


def set_current_utc(dt):
    """Pin the authoritative now. dt must be a timezone-aware datetime (UTC)."""
    global _current_utc
    _current_utc = dt.astimezone(timezone.utc)


def now():
    """Return the authoritative current UTC moment as an aware datetime."""
    if _current_utc is not None:
        return _current_utc
    return datetime.now(timezone.utc)


def now_iso_clock():
    """current_utc rendered ISO 8601 UTC with three fractional digits."""
    dt = now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
