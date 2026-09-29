"""In-memory data store, id/sequence/timestamp helpers and the logical clock.

The store starts completely empty on every boot: no entity is ever seeded,
preloaded or hardcoded here.  Every row a test needs is created through the
declared API surface.
"""

import itertools
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

# Before the clock has ever been set it reads exactly this instant (PRD 2.5)
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

UTC = timezone.utc


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.seasons = {}
        self.ensembles = {}
        self.section_quotas = {}
        self.members = {}
        self.panelists = {}
        self.audition_slots = {}
        self.auditions = {}
        self.panel_scores = {}
        self.placements = {}
        self.seat_assignments = {}
        self.tuition_accounts = {}
        self.ensemble_events = {}
        self.event_participations = {}
        # logical clock
        self.clock = DEFAULT_CLOCK
        # per-instrument blind code sequence
        self.blind_seq = {}
        self._counter = itertools.count(1)


db = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(db._counter)


def now_utc():
    return datetime.now(tz=UTC)


def clock_now():
    return db.clock


def set_clock(dt):
    db.clock = dt.astimezone(UTC)


def iso3(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def base_row(with_version=True):
    ts = now_utc()
    row = {
        "id": new_id(),
        "created_at": ts,
        "_seq": next_seq(),
    }
    if with_version:
        row["updated_at"] = ts
        row["version"] = 1
    return row


def hours(n):
    return timedelta(hours=n)


def order_key(row):
    """Canonical `created_at ASC` ordering key; row id is never a tie-break."""
    return (row["created_at"], row["_seq"])
