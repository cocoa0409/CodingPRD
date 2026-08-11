"""The logical clock and the single instant-rendering function.

ADJUDICATION -- timestamp rendering (recurring implementation-generator bug D1).
Exactly one function renders an instant to JSON: `render_instant()`.  The rule:

  * Every SERVER-STAMPED instant (anything derived from the logical clock, and
    every instant computed from one -- `ends_at`, `sla_deadline_at`,
    `rebind_eligible_at`, `api_request_timestamp`, ...) renders in the PRD §2.4
    canonical form `YYYY-MM-DDTHH:MM:SS.mmmZ`, always three fractional digits.
  * Every CALLER-SUPPLIED instant that is stored on a row as an input field
    (`IdentityDocument.expires_at`, `BreachEvent.breach_date`,
    `BreachEvent.disclosed_at`) is echoed back VERBATIM -- byte-for-byte the
    string the caller sent.  PRD §2.4 constrains only server-minted fields, so
    normalising caller input would be an invention.
  * The logical clock endpoint echoes literals as well: `current_utc` is the
    caller's `to_iso8601` string verbatim and `previous_utc` is whatever literal
    was in force before (initially exactly `2026-05-01T00:00:00Z`, the literal
    PRD §2.4 states).

Real wall-clock time is never read for business logic.
"""

from datetime import datetime, timedelta, timezone

from constants import CLOCK_DEFAULT_LITERAL


class LogicalClock:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._literal = CLOCK_DEFAULT_LITERAL
        self._value = parse_instant(CLOCK_DEFAULT_LITERAL)

    @property
    def now(self) -> datetime:
        return self._value

    @property
    def literal(self) -> str:
        return self._literal

    def set(self, dt: datetime, literal: str):
        prev_literal = self._literal
        self._value = dt
        self._literal = literal
        return prev_literal


def parse_instant(text):
    """Parse an ISO-8601 instant. Returns None when the text is not one."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date_or_instant(text):
    """Parse either a calendar date or a full instant (for `date_of_birth`)."""
    return parse_instant(text)


def render_instant(dt):
    """THE single renderer for server-stamped instants: `....mmmZ`."""
    if dt is None:
        return None
    if isinstance(dt, str):
        # A verbatim caller literal that reached the renderer unchanged.
        return dt
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def plus_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(seconds=days * 86400)


def plus_hours(dt: datetime, hours: int) -> datetime:
    return dt + timedelta(seconds=hours * 3600)


def whole_days_between(earlier: datetime, later: datetime) -> int:
    """floor((later - earlier) / 86400 seconds) -- PRD §2.9 day arithmetic."""
    delta = (later - earlier).total_seconds()
    return int(delta // 86400)


CLOCK = LogicalClock()


def now() -> datetime:
    return CLOCK.now
