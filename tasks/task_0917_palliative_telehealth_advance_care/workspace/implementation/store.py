"""In-memory store, the logical clock, and the single datetime rendering rule.

TIMESTAMP RENDERING (PRD 2.4) — adjudicated once, here:
  * every instant the server holds is a timezone-aware UTC ``datetime`` object;
  * every instant the server emits — ``created_at``, ``updated_at``, a caller
    supplied instant echoed back, a clock stamp, and a derived instant such as
    ``response_due_at`` — is rendered by :func:`fmt_dt` as
    ``YYYY-MM-DDTHH:MM:SS.mmmZ`` (exactly three fractional digits, literal Z);
  * ``date_of_birth`` is not a datetime: it is stored and echoed as supplied.

No entity data is ever seeded: every dict below starts empty on each boot.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

from errors import ERR_VALIDATION, api_error

UTC = timezone.utc

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"([Zz]|[+-]\d{2}:?\d{2})?)?$"
)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_iso(value):
    """Parse any valid ISO 8601 instant into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hh, mm, ss, frac, off = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        dt = datetime(
            int(year), int(month), int(day),
            int(hh or 0), int(mm or 0), int(ss or 0), micro, tzinfo=UTC,
        )
    except ValueError:
        return None
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        body = off[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * delta
    return dt


def fmt_dt(dt):
    """The one and only datetime rendering call site."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


class Store:
    """Plain in-memory storage. Reset wholesale on every process boot."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = parse_iso("2026-05-01T00:00:00Z")
        self._seq = 0
        self.patients = {}
        self.referrals = {}
        self.surrogates = {}
        self.documents = {}
        self.code_status_orders = {}
        self.care_plans = {}
        self.symptom_assessments = {}
        self.conferences = {}
        self.medication_orders = {}
        self.dme_inventory = {}
        self.dme_orders = {}
        self.hospice_elections = {}
        self.escalations = {}
        self.claims = {}

    # ---------------------------------------------------------------- clock
    def now(self):
        return self.clock

    def set_clock(self, dt):
        self.clock = dt

    # ---------------------------------------------------------------- rows
    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_row(self, fields):
        """Build a row: id first, declared fields, then the four common props."""
        now = self.now()
        row = {"id": str(uuid.uuid4())}
        row.update(fields)
        row["created_at"] = now
        row["updated_at"] = now
        row["version"] = 1
        row["_seq"] = self.next_seq()
        return row


store = Store()


def sort_key(row):
    """Deterministic list ordering: created_at ascending, insertion order breaks ties."""
    return (row["created_at"], row["_seq"])


def ordered(rows):
    return sorted(rows, key=sort_key)


def require_dt(value, field):
    dt = parse_iso(value)
    if dt is None:
        raise api_error(ERR_VALIDATION, "%s is not a valid ISO 8601 instant." % field)
    return dt


def days(n):
    return timedelta(days=n)


def minutes(n):
    return timedelta(minutes=n)


def hours(n):
    return timedelta(hours=n)
