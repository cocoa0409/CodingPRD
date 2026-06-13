"""Timestamps and the logical (test-driveable) clock.

Two distinct concepts:

  * Real wall-clock timestamps stamped into `created_at` / `updated_at` and the
    response envelope's `api_request_timestamp`. These always use the real
    system time so that creation order (used for default `created_at ASC`
    sorting and the deposit waterfall) is monotonic regardless of the logical
    clock.

  * The logical "current" UTC instant (PRD §2.10) that drives quote expiry.
    It is advanced by POST /_clock/set_current_utc. When unset it tracks real
    time.

All timestamps are ISO 8601 UTC with exactly three fractional digits (PRD
§2.4): e.g. 2025-05-24T10:30:00.123Z
"""
from datetime import datetime, timezone

# Monotonic sequence so two entities created within the same millisecond still
# have a deterministic creation order for sorting / waterfall ordering.
_seq = 0

# Logical clock override (a tz-aware datetime) or None when tracking real time.
_logical_now = None


def _fmt(dt):
    # Force UTC, millisecond precision, trailing Z.
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def now_iso_realtime():
    return _fmt(datetime.now(timezone.utc))


def next_seq():
    global _seq
    _seq += 1
    return _seq


def set_logical_now(iso_str):
    """Set the logical clock from an ISO 8601 string (PRD §2.10 / §3.9)."""
    global _logical_now
    _logical_now = parse_iso(iso_str)


def logical_now():
    if _logical_now is not None:
        return _logical_now
    return datetime.now(timezone.utc)


def parse_iso(s):
    """Parse an ISO 8601 instant into a tz-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset; assumes UTC when naive.
    """
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reset():
    """Reset module state (used implicitly by a fresh process boot)."""
    global _seq, _logical_now
    _seq = 0
    _logical_now = None
