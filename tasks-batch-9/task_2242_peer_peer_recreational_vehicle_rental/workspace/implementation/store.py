"""In-memory data store and the logical clock.

Storage is process-local Python dicts keyed by id. Nothing is persisted and
nothing is seeded: the store is empty on every boot.
"""

import calendar
import uuid
from datetime import datetime, timezone, date, time

# PRD 2.5 — the server's startup default logical clock.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "owners",
    "renters",
    "listings",
    "vehicle_documents",
    "renter_qualifications",
    "protection_plans",
    "cancellation_policies",
    "pricing_seasons",
    "campgrounds",
    "bookings",
    "delivery_assignments",
    "meter_readings",
    "trip_photos",
    "damage_claims",
    "ledger_entries",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --------------------------------------------------------------- time utils ---
def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def now():
    return db.clock


def now_iso():
    return iso(db.clock)


def clock_date():
    return db.clock.astimezone(timezone.utc).date()


def parse_dt(value):
    """Parse an ISO 8601 instant; returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def at_time(day, hh, mm, ss):
    return datetime.combine(day, time(hh, mm, ss), tzinfo=timezone.utc)


def add_months(dt, months):
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


# ------------------------------------------------------------ record helpers ---
def new_record(with_version=True, **fields):
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "_seq": db.next_seq(),
    }
    if with_version:
        rec["updated_at"] = now_iso()
        rec["version"] = 1
    rec.update(fields)
    return rec


def touch(rec):
    """Record a mutation: refresh updated_at and increment version."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 0) + 1


def creation_order(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
