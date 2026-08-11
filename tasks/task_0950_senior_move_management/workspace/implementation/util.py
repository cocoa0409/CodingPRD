"""Timestamp rendering, date arithmetic and round-half-up numerics.

TIMESTAMP RENDERING - the single three-case rule used everywhere:

  (a) Server-written instants (``created_at``, ``updated_at``, ``closed_at_utc``,
      ``approved_at_utc``, ``frozen_at_utc``, ``started_at_utc``,
      ``completed_at_utc``, ``issued_at_utc``, ``finalized_at_utc``, the
      ``checked_out_at_utc`` the move-day cascade stamps) are taken from the
      logical clock and rendered canonically as ``YYYY-MM-DDTHH:MM:SS.mmmZ``
      - ISO 8601 UTC with exactly three fractional digits (PRD 2.4, 2.5).

  (b) Caller-supplied instants echoed back (``scheduled_move_start_utc``,
      ``scheduled_start_utc``, ``effective_from_utc``, ``effective_to_utc``,
      ``checked_in_at_utc``, ``checked_out_at_utc`` from ``at_utc``,
      ``performed_at_utc``, ``started_at_utc``/``ended_at_utc`` on a TimeEntry)
      are stored and returned VERBATIM, byte for byte as the caller wrote them.
      PRD 2.5: "an instant supplied by a client and later echoed back is the
      same instant, not a re-derived wall-clock value."

  (c) Instants DERIVED from a caller-supplied instant (``freeze_at_utc`` and
      ``move_freeze_at_utc`` = start - 72h, ``due_at_utc`` = created_at + SLA)
      are rendered canonically, exactly like case (a) - three fractional digits.
      They are new instants, not echoes, and both derivations are pinned to
      "ISO 8601 UTC with three fractional digits". A derived instant therefore
      never inherits the rendering style of the input it came from.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, ROUND_CEILING

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"([Zz]|[+-]\d{2}:\d{2})$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def new_id():
    return str(uuid.uuid4())


def is_datetime_string(value):
    return isinstance(value, str) and bool(_DT_RE.match(value))


def is_date_string(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return False
    try:
        parse_date(value)
    except Exception:
        return False
    return True


def parse_dt(value):
    """ISO 8601 instant -> aware UTC datetime. Raises ValueError when malformed."""
    if not is_datetime_string(value):
        raise ValueError("not an ISO 8601 instant: %r" % (value,))
    text = value.strip()
    if text[-1] in "Zz":
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    y, m, d = value.split("-")
    return date(int(y), int(m), int(d))


def fmt_dt(dt):
    """Canonical rendering: ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def fmt_date(d):
    return d.isoformat()


def dt_date(value):
    """Calendar date (UTC) of an instant string."""
    return parse_dt(value).date()


def shift_hours(value, hours):
    """Derived instant: caller instant +/- N hours, rendered canonically (case c)."""
    return fmt_dt(parse_dt(value) + timedelta(hours=hours))


# ---------------------------------------------------------------------------
# numerics - all rounding in this system is round-half-up (PRD 2.8)
# ---------------------------------------------------------------------------

def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up to ``places`` decimal places, returning a Decimal."""
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def trunc(value, places):
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_DOWN)


def ceil_div(numerator, denominator):
    return int((D(numerator) / D(denominator)).quantize(Decimal(1), rounding=ROUND_CEILING))


def num(value, places=2):
    """Serialise a Decimal/number as a JSON number with the given precision."""
    return float(rhu(value, places))
