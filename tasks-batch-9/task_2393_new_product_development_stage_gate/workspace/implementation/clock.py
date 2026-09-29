"""The logical clock (PRD §2.4) and audit-timestamp minting.

Two distinct notions of time live here and must not be confused:

* **The logical clock** — ``current_utc``. Starts at ``2026-08-01T00:00:00Z``
  on a fresh process and moves only when ``POST /_clock/set_current_utc`` is
  called. Every lead-time comparison, window containment test, due-date check
  and "has this instant been reached yet" precondition reads this.

* **Audit stamps** — ``created_at`` and ``updated_at`` are minted from the
  logical clock (``audit_stamp``), because "Time is not read from the host"
  (PRD §2.4): a row written while the clock stands still carries exactly that
  instant, rewinding the clock recomputes no stored stamp, and rows created at
  one logical instant legitimately *share* a ``created_at`` — which is why
  §2.6 provides an ordering fallback for rows sharing a timestamp at all.
  Ordering ties therefore resolve on the insertion ordinal, never on ``id``.

* ``api_request_timestamp`` is the one stamp minted off the host wall clock
  (``stamp``), through a monotonic guard forcing strictly increasing 1 ms
  steps; it labels the HTTP exchange rather than any stored row.
"""

import re
import threading
from datetime import datetime, timedelta, timezone

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

CLOCK_INITIAL_RAW = "2026-08-01T00:00:00Z"
CLOCK_INITIAL_DT = datetime(2026, 8, 1, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# audit stamps
# ---------------------------------------------------------------------------
_stamp_lock = threading.Lock()
_last_ms = 0


def format_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def stamp():
    """Next strictly-increasing audit timestamp."""
    global _last_ms
    with _stamp_lock:
        ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if ms <= _last_ms:
            ms = _last_ms + 1
        _last_ms = ms
    return format_dt(_EPOCH + timedelta(milliseconds=ms))


# ---------------------------------------------------------------------------
# ISO 8601 parsing
# ---------------------------------------------------------------------------
_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?)?$"
)


def parse_iso(value):
    """Parse an ISO-8601 datetime (or bare date) into an aware UTC datetime.

    Returns ``None`` when the value is not a legal ISO-8601 instant; callers
    turn that into ``ERR_INVALID_REQUEST``.
    """
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, tz = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        dt = datetime(
            int(year), int(month), int(day),
            int(hour or 0), int(minute or 0), int(second or 0), micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * offset
    return dt


# ---------------------------------------------------------------------------
# the logical clock
# ---------------------------------------------------------------------------
_state = {"raw": CLOCK_INITIAL_RAW, "dt": CLOCK_INITIAL_DT}


def current_dt():
    """The logical instant, as an aware UTC datetime."""
    return _state["dt"]


def current_raw():
    """The logical instant exactly as the last setter supplied it."""
    return _state["raw"]


def set_current(raw, dt):
    _state["raw"] = raw
    _state["dt"] = dt


def reset():
    _state["raw"] = CLOCK_INITIAL_RAW
    _state["dt"] = CLOCK_INITIAL_DT


def audit_stamp():
    """``created_at`` / ``updated_at``: the logical instant, never host time."""
    return format_dt(current_dt())
