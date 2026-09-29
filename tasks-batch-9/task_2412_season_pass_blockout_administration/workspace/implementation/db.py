"""In-memory data store.

Storage is process-local Python dictionaries only.  Nothing is persisted and
nothing is seeded: the store starts completely empty on every boot.
"""

import calendar
import json
import uuid
from datetime import date, datetime, timedelta, timezone

TABLES = [
    "pass_programs",
    "pass_tiers",
    "park_days",
    "blockout_assignments",
    "passholders",
    "season_passes",
    "payment_plans",
    "installments",
    "reservations",
    "visits",
    "sharing_cases",
    "upgrade_orders",
]

# PRD 2.5 - the logical clock default.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def parse_instant(value):
    """Parse an ISO 8601 timestamp; raises ValueError when malformed."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if "T" not in text:
        raise ValueError("not a timestamp")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_day(value):
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if len(text) != 10:
        raise ValueError("bad length")
    return datetime.strptime(text, "%Y-%m-%d").date()


def fmt_day(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def add_months(d, months):
    """Add calendar months, clamping down to the last day of a short month."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


class Store(object):
    def __init__(self):
        self.lock_hint = None
        self.reset()

    def reset(self):
        for table in TABLES:
            setattr(self, table, {})
        self.clock = DEFAULT_CLOCK
        self.clock_echo = fmt_instant(DEFAULT_CLOCK)
        self._media_seq = 0
        self._last_ms = 0
        self._snapshot = None
        self._created = set()
        self._forced = set()

    # ---------- clock ----------
    def now(self):
        """The logical clock instant (PRD 2.5)."""
        return self.clock

    def today(self):
        return self.clock.date()

    def set_clock(self, dt, echo):
        self.clock = dt
        self.clock_echo = echo

    # ---------- system timestamps ----------
    def _next_ms(self):
        ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if ms <= self._last_ms:
            ms = self._last_ms + 1
        self._last_ms = ms
        return ms

    def stamp(self):
        return fmt_instant(datetime.fromtimestamp(self._next_ms() / 1000.0, timezone.utc))

    # ---------- records ----------
    def insert(self, table, fields):
        record = dict(fields)
        record["id"] = str(uuid.uuid4())
        stamp = self.stamp()
        record["created_at"] = stamp
        record["updated_at"] = stamp
        record["version"] = 1
        getattr(self, table)[record["id"]] = record
        self._created.add(record["id"])
        return record

    def next_media_number(self):
        self._media_seq += 1
        return "SP-%06d" % self._media_seq

    def rows(self, table):
        """Rows in insertion order (== created_at ascending)."""
        return list(getattr(self, table).values())

    # ---------- version / updated_at bookkeeping (PRD 2.4 + 2.6) ----------
    def begin(self):
        self._created = set()
        self._forced = set()
        self._snapshot = self._capture()

    def force_touch(self, record):
        self._forced.add(record["id"])

    def _capture(self):
        from serializers import capture_all

        return capture_all(self)

    def commit(self):
        """Bump version / updated_at on every record this request changed."""
        if self._snapshot is None:
            return
        after = self._capture()
        stamp = self.stamp()
        for key, state in after.items():
            table, record_id = key
            if record_id in self._created:
                continue
            if state != self._snapshot.get(key) or record_id in self._forced:
                record = getattr(self, table).get(record_id)
                if record is not None:
                    record["version"] += 1
                    record["updated_at"] = stamp
        self._snapshot = None


db = Store()
