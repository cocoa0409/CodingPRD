"""The logical clock and THE single instant-rendering policy for the whole API.

PRD 2.4: "The server runs on a **logical clock**, never on wall-clock time.
Before any caller sets it, the clock reads exactly `2026-05-01T00:00:00Z`."

=========================  INSTANT RENDERING POLICY  =========================
Every instant that ever reaches a JSON response is rendered by exactly one of
the three functions below.  Nothing else in this codebase formats a datetime.

(a) SERVER-MINTED instants -> `canonical(dt)`
    `created_at`, `updated_at` and `meta.api_request_timestamp`.
    PRD 2.4: "a `created_at` timestamp in ISO 8601 UTC with three fractional
    digits", and PRD 2.2 for `api_request_timestamp`.  Rendered as
    YYYY-MM-DDTHH:MM:SS.mmmZ -- always exactly three fractional digits.

(b) CALLER-SUPPLIED instants -> stored and echoed BYTE-VERBATIM.
    `date_of_birth`, `intake_datetime`, `scheduled_at`, `issued_at`,
    `checked_at`, `scheduled_depart_at`, `scheduled_arrive_at`,
    PartnerCommitment.`expires_at`, and the clock's own `to_iso8601` /
    `current_utc`.  The exact bytes the caller sent come back out.  This is
    the rule the recurring "generated timestamps rendered differently from the
    input dates" defect violates.

(c) DERIVED instants -> `derive(dt, source_raw)`
    Rendered in the STYLE of the source string they derive from (same number
    of fractional digits, same UTC suffix spelling):
      IntakeRecord.hold_expires_at            <- intake_datetime
      FosterApplication.home_check_passed_at  <- checked_at (verbatim)
      FosterApplication.home_check_expires_at <- checked_at
      HealthCertificate.expires_at            <- issued_at
    Instants stamped from the LOGICAL CLOCK (released_at, recorded_at,
    finalized_at, started_at, aborted_at, departed_at, arrived_at, ended_at,
    started_at, screened_at, split_approved_at, completed_at, reversed_at,
    returned_at, rabies_vaccinated_at) derive from the clock string the caller
    last set, so they are rendered in that string's style -- i.e. `stamp()`
    hands back the caller's own bytes.  A server whose clock was never set
    stamps the default "2026-05-01T00:00:00Z".
=============================================================================
"""

from datetime import datetime, timedelta, timezone
import re

CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2}))?"
    r"(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})$"
)


class BadInstant(ValueError):
    """Raised when a string does not parse as an ISO 8601 UTC instant."""


def parse(raw):
    """Parse an ISO 8601 instant into an aware UTC datetime.  Raises BadInstant."""
    if not isinstance(raw, str):
        raise BadInstant("not a string")
    m = _ISO_RE.match(raw.strip())
    if not m:
        raise BadInstant(raw)
    year, month, day, hh, mm = (int(m.group(i)) for i in (1, 2, 3, 4, 5))
    ss = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    off = m.group(8)
    try:
        base = datetime(year, month, day, hh, mm, ss, micro, tzinfo=timezone.utc)
    except ValueError as exc:
        raise BadInstant(raw) from exc
    if off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        off_body = off[1:].replace(":", "")
        delta = timedelta(hours=int(off_body[:2]), minutes=int(off_body[2:]))
        base = base - sign * delta
    return base


def style_of(raw):
    """Return the (fractional-digit-count, utc-suffix) style of an instant string."""
    if not isinstance(raw, str):
        return (3, "Z")
    m = _ISO_RE.match(raw.strip())
    if not m:
        return (3, "Z")
    frac = m.group(7) or ""
    digits = len(frac) - 1 if frac else 0
    suffix = m.group(8)
    if suffix in ("Z", "z"):
        suffix = "Z"
    return (digits, suffix)


def render(dt, style):
    """Render an aware UTC datetime in the given (frac_digits, suffix) style."""
    dt = dt.astimezone(timezone.utc)
    body = dt.strftime("%Y-%m-%dT%H:%M:%S")
    digits, suffix = style
    if digits:
        micro = "%06d" % dt.microsecond
        body += "." + (micro + "000000")[:digits] if digits <= 6 else "." + micro + "0" * (digits - 6)
    return body + suffix


def canonical(dt):
    """(a) Server-minted rendering: ISO 8601 UTC with exactly three fractional digits."""
    return render(dt, (3, "Z"))


def derive(dt, source_raw):
    """(c) Derived rendering: the style of the source string this instant derives from."""
    return render(dt, style_of(source_raw))


def plus_days(dt, days):
    """Advance an instant by whole 24-hour periods (PRD 2.8: calendar-free arithmetic)."""
    return dt + timedelta(days=days)


def elapsed_days(later, earlier):
    """Whole elapsed days, fractional day discarded (PRD 2.8).

    timedelta normalises so that `.days` is already floor(total/86400), which
    is exactly "take the difference and discard any fractional day".
    """
    return (later - earlier).days


class LogicalClock(object):
    """The server's logical clock.  Never falls back to wall-clock time."""

    def __init__(self):
        self._raw = CLOCK_DEFAULT_UTC
        self._dt = parse(CLOCK_DEFAULT_UTC)

    @property
    def raw(self):
        """The clock instant as the caller last spelled it (byte-verbatim)."""
        return self._raw

    @property
    def dt(self):
        """The clock instant as an aware UTC datetime."""
        return self._dt

    def set(self, raw):
        parsed = parse(raw)
        self._raw = raw
        self._dt = parsed
        return self._raw

    def stamp(self):
        """(c) A clock-derived instant, rendered in the clock string's own style."""
        return self._raw

    def stamp_style(self):
        return style_of(self._raw)


CLOCK = LogicalClock()


def now():
    return CLOCK.dt


def now_raw():
    return CLOCK.raw


def stamp():
    return CLOCK.stamp()


def reset_for_tests():
    CLOCK.__init__()
