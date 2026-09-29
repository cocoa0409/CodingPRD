"""In-memory data store and the server-held logical clock.

The store starts completely empty on every boot: no entity is ever seeded,
preloaded or hardcoded.  Every entity a caller needs is built through the
public API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone, timedelta

# PRD 2.5: before any client sets it, the logical clock reads exactly this
# instant, and the server never falls back to the host wall clock for any
# date-/time-dependent rule.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "funds",
    "properties",
    "stands",
    "cruise_plots",
    "underwriting_cases",
    "harvest_blocks",
    "carbon_projects",
    "carbon_dedications",
    "hbu_parcels",
    "recreational_leases",
    "certification_audits",
    "audit_findings",
    "hazard_events",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


store = Store()


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def logical_now():
    return store.clock


def logical_now_iso():
    return iso(store.clock)


def logical_date():
    return store.clock.astimezone(timezone.utc).date()


def set_clock(dt):
    store.clock = dt.astimezone(timezone.utc)


def real_now_iso():
    return iso(datetime.now(timezone.utc))


def base_fields(with_version=True):
    """Common system fields for a freshly created resource."""
    rec = {
        "id": new_id(),
        "created_at": logical_now_iso(),
        "_seq": store.next_seq(),
    }
    if with_version:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Record a mutation: refresh updated_at and bump version."""
    rec["updated_at"] = logical_now_iso()
    rec["version"] = rec.get("version", 1) + 1


def sort_key(rec):
    """List ordering: created_at ascending, insertion sequence as tie break."""
    return (rec.get("created_at") or "", rec.get("_seq") or 0)


def sorted_records(records):
    return sorted(records, key=sort_key)


def days_between(a, b):
    """Whole days from date a to date b."""
    return (b - a).days


def add_years(d, years):
    """Advance a date by whole calendar years, clamping Feb 29."""
    year = d.year + years
    month = d.month
    day = d.day
    while True:
        try:
            return d.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


def add_months(d, months):
    """Advance a date by whole calendar months, clamping the day of month."""
    total = (d.year * 12 + (d.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    day = d.day
    while True:
        try:
            return d.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


TIMEDELTA = timedelta
