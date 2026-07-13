"""In-memory data store + the server logical clock.

Storage is process-local Python dicts keyed by id.  Nothing is persisted and
NOTHING is seeded: every entity is created by callers through the declared API
surface.  Killing the process erases all state.
"""
import itertools
import threading
import uuid

from util import fmt_dt, parse_dt

# PRD §2.4 — before any /_clock/set_current_utc call the clock reads this value,
# and it never falls back to wall-clock time.
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"


class Clock:
    """Server logical clock.  Keeps the raw ISO string the admin supplied so that
    system-stamped instants (purchased_at / effective_to / filed_at) round-trip
    exactly the value the clock was set to."""

    def __init__(self):
        self.raw = DEFAULT_CLOCK_ISO
        self.dt = parse_dt(DEFAULT_CLOCK_ISO)

    def set(self, iso_string):
        self.dt = parse_dt(iso_string)
        self.raw = iso_string
        return self.raw

    def now(self):
        """Current logical instant as a tz-aware datetime."""
        return self.dt

    def now_iso(self):
        """Current logical instant as the raw ISO string it was set with."""
        return self.raw

    def stamp(self):
        """Canonical 3-fractional-digit rendering of the current logical instant."""
        return fmt_dt(self.dt)


class DB:
    def __init__(self):
        self.fleet_accounts = {}
        self.vehicles = {}
        self.drivers = {}
        self.fuel_cards = {}
        self.card_assignments = {}
        self.transactions = {}
        self.fraud_alerts = {}
        self.telematics_faults = {}
        self.ifta_reports = {}
        self.clock = Clock()
        self.lock = threading.RLock()
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = DB()


def new_id():
    return str(uuid.uuid4())


def base_record():
    """Common system-managed fields (PRD §2.5): id, created_at, updated_at, version."""
    stamp = db.clock.stamp()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(record):
    """Every mutation refreshes updated_at and increments version by one."""
    record["updated_at"] = db.clock.stamp()
    record["version"] = record.get("version", 1) + 1


def sort_key(record):
    """Default list ordering: created_at ascending, stable by insertion order."""
    return (record["created_at"], record["_seq"])
