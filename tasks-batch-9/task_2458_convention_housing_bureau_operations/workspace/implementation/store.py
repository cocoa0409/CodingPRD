"""In-memory data store, logical housing clock and common-field helpers.

The store is empty on every boot.  Nothing is seeded, preloaded or hardcoded:
every entity is created by an API call.
"""

import threading
import uuid
from datetime import date, datetime, timedelta, timezone

# PRD §2.5 — at server startup the logical clock reads exactly 2026-08-01T00:00:00Z.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

ROLES = (
    "BureauCoordinator",
    "BureauController",
    "HotelManager",
    "EventOrganizer",
    "Attendee",
    "ComplianceOfficer",
)
ALL_ROLES = list(ROLES)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.events = {}
        self.hotels = {}
        self.hotel_blocks = {}
        self.sub_blocks = {}
        self.attendees = {}
        self.reservations = {}
        self.transmissions = {}
        self.pickup_reports = {}
        self.reductions = {}
        self.vendors = {}
        self.incidents = {}
        self.invoices = {}
        self._carve_seq = 0
        self._intake_seq = 0
        self._insert_seq = 0
        self.clock = CLOCK_EPOCH

    def next_carve_seq(self):
        self._carve_seq += 1
        return self._carve_seq

    def next_intake_seq(self):
        self._intake_seq += 1
        return self._intake_seq

    def next_insert_seq(self):
        self._insert_seq += 1
        return self._insert_seq


STORE = Store()


# ---------------------------------------------------------------- timestamps


def iso_ms(dt):
    """ISO 8601 UTC instant with exactly three fractional digits (PRD §2.4)."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def clock_iso():
    return iso_ms(STORE.clock)


def parse_iso_date(value):
    """Strict YYYY-MM-DD parse; returns a datetime.date or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_iso_datetime(value):
    """Lenient ISO-8601 instant parse; returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    candidate = raw
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        # allow a bare date
        d = parse_iso_date(raw)
        if d is None:
            return None
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def midnight_utc(date_value):
    """Midnight UTC of an ISO date string or a datetime.date."""
    d = date_value if isinstance(date_value, date) else parse_iso_date(date_value)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def clock_before_date(date_value):
    """True when the logical clock is strictly before <date> at 00:00:00Z."""
    return STORE.clock < midnight_utc(date_value)


def clock_at_or_after_date(date_value):
    """True when the logical clock reads <date> 00:00:00Z or any later instant."""
    return STORE.clock >= midnight_utc(date_value)


def days_between(start, end):
    a = start if isinstance(start, date) else parse_iso_date(start)
    b = end if isinstance(end, date) else parse_iso_date(end)
    return (b - a).days


def date_shift(date_value, days):
    d = date_value if isinstance(date_value, date) else parse_iso_date(date_value)
    return d + timedelta(days=days)


# ------------------------------------------------------------- record helpers


def new_id():
    return str(uuid.uuid4())


def base_record(mutable=True):
    """Common fields.  Mutable resources carry updated_at + version; the two
    append-only ledgers (rooming-list batches, pickup reports) carry only
    id and created_at (PRD §2.4)."""
    now = clock_iso()
    rec = {"id": new_id(), "created_at": now}
    if mutable:
        rec["updated_at"] = now
        rec["version"] = 1
    rec["_seq"] = STORE.next_insert_seq()
    return rec


def touch(rec):
    """Register a mutation: refresh updated_at and bump version by exactly 1."""
    rec["updated_at"] = clock_iso()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def sort_created(items):
    """Default list ordering: created_at ASC, insertion order as a stable
    tie-break (created_at can repeat because it reads the logical clock)."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
