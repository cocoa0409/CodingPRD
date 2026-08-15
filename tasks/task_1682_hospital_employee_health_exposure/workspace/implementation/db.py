"""In-memory data store and logical clock. Fresh per process; nothing is seeded."""
from datetime import datetime, timezone

from util import fmt_dt, new_id


class LogicalClock:
    """The system never reads wall-clock time; all 'now' semantics resolve here.

    Startup default is exactly 2026-08-01T00:00:00Z.
    """

    def __init__(self):
        self.current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.employees = {}
        self.screenings = {}
        self.titers = {}
        self.cycles = {}
        self.holds = {}
        self.cases = {}
        self.pep_regimens = {}
        self.followups = {}
        self.restrictions = {}
        self.clearances = {}
        self.events = {}
        self.contacts = {}
        self.injuries = {}
        self.campaigns = {}
        self.participations = {}
        self.wc_sequence = 0  # counts WC_SUBMITTED transitions in order, 1-based
        self._seq = 0  # internal insertion counter for stable ordering

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()
clock = LogicalClock()


def now():
    return clock.current


def base_fields(with_version=True):
    """Common system-managed fields for a new primary resource."""
    t = now()
    ent = {"id": new_id(), "created_at": t, "_seq": store.next_seq()}
    if with_version:
        ent["updated_at"] = t
        ent["version"] = 1
    return ent


def touch(ent):
    """version increments by one on every mutation; updated_at refreshes."""
    ent["version"] += 1
    ent["updated_at"] = now()


def serialize(ent):
    out = {}
    for k, v in ent.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        elif isinstance(v, list):
            out[k] = list(v)
        else:
            out[k] = v
    return out
