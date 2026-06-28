"""Logical clock + timestamp helpers.

PRD §2.4: Time is governed by a logical clock rather than wall-clock time.
The server's logical clock starts at 2026-01-01T00:00:00Z; before any
clock-setting call is made the clock reads exactly this default and never
falls back to the machine's real time. A SchedulingCoordinator advances the
clock to a supplied to_iso8601 instant; that instant is what every temporal
gate (check-in timing, no-show timing) is evaluated against.

The envelope's api_request_timestamp (PRD §2.2) is a *server-generated*
timestamp; it is distinct from the logical clock and uses real UTC time so
each request gets a unique-ish stamp. Only the logical clock drives temporal
gates.
"""
from datetime import datetime, timezone

# Default logical-clock instant — PRD §2.4.
_DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"

# Module-level state. Reset on every fresh process boot (in-memory only).
_logical_now = None  # set lazily to the default below


def parse_iso(value):
    """Parse an ISO 8601 UTC timestamp into an aware datetime.

    Accepts a trailing 'Z' or an explicit +00:00 offset, with or without
    fractional seconds. Returns a timezone-aware datetime in UTC. Raises
    ValueError on a malformed value.
    """
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Format an aware datetime as ISO 8601 UTC with 3 fractional digits + Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def format_iso_like(dt, reference_iso):
    """Format `dt` as ISO 8601 UTC, mirroring the fractional precision of
    `reference_iso`.

    `effective_end_utc` is defined (PRD §3.2 / SCAFFOLD) as the
    `scheduled_start_utc` advanced by whole minutes, so it should be rendered at
    the same precision as that input instant rather than gaining a spurious
    `.000` fractional part. When the reference carries no fractional seconds the
    result is second-precision (`...:00Z`); otherwise it keeps 3 fractional
    digits.
    """
    dt = dt.astimezone(timezone.utc)
    ref = reference_iso.strip() if isinstance(reference_iso, str) else ""
    body = ref[:-1] if ref.endswith(("Z", "z")) else ref
    has_fraction = "." in body
    if has_fraction:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def now_iso_realish():
    """ISO 8601 UTC stamp (3 fractional digits) for the response envelope.

    Uses real wall-clock UTC; this is NOT the logical clock.
    """
    return format_iso(datetime.now(timezone.utc))


def get_logical_now():
    """Return the current logical-clock datetime (aware UTC)."""
    global _logical_now
    if _logical_now is None:
        _logical_now = parse_iso(_DEFAULT_CLOCK_ISO)
    return _logical_now


def set_logical_now(iso_value):
    """Advance the logical clock to the supplied ISO instant."""
    global _logical_now
    _logical_now = parse_iso(iso_value)
    return _logical_now
