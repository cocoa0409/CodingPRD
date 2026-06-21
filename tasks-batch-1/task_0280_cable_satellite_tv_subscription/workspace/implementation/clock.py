"""Server clock.

Two distinct notions of time:

  * The *wall* clock (used for created_at / updated_at / api_request_timestamp)
    is always the real UTC time, with ISO 8601 + 3 fractional digits (PRD §2.4).
  * The *test-driving* clock (PRD §2.12) is a settable instant used ONLY for
    deterministic service-visit window validation. A BillingAdmin sets it via
    POST /_clock/set_current_utc { to_iso8601 }. Until set, it falls back to the
    real wall clock.

In-memory only; resets on every process boot.
"""

from datetime import datetime, timezone

# The test-driving clock instant (a timezone-aware datetime), or None = use wall.
_test_clock = None


def _utcnow():
    return datetime.now(timezone.utc)


def now_iso8601():
    """Real wall-clock UTC timestamp, ISO 8601 with exactly 3 fractional digits."""
    dt = _utcnow()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def set_test_clock(dt):
    """Set the test-driving clock to a timezone-aware datetime instant."""
    global _test_clock
    _test_clock = dt


def current_visit_clock():
    """The current instant used for visit-window validation (test clock or wall)."""
    if _test_clock is not None:
        return _test_clock
    return _utcnow()


def parse_iso8601(value):
    """Parse an ISO 8601 string into a timezone-aware UTC datetime, or None on failure."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # Normalize trailing Z to +00:00 for fromisoformat.
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def to_iso8601(dt):
    """Format a timezone-aware datetime to ISO 8601 UTC with 3 fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
