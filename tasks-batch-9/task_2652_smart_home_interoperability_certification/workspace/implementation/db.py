"""In-memory store, logical programme clock, and common-field helpers.

Storage is process-local Python dicts keyed by id. Nothing is persisted and
nothing is seeded: the store starts completely empty on every boot.
"""

import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.5: the clock starts at exactly this instant on every boot and never
# falls back to the host wall clock.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.specifications = {}
        self.feature_sets = {}
        self.members = {}
        self.laboratories = {}
        self.submissions = {}
        self.test_plans = {}
        self.test_sessions = {}
        self.plugfests = {}
        self.participations = {}
        self.listings = {}
        self.cases = {}
        self.clock = CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def now():
    return store.clock


def set_clock(instant):
    store.clock = instant


def new_id():
    return str(uuid.uuid4())


def plus_days(instant, days):
    return instant + timedelta(seconds=days * 86400)


# ---------------------------------------------------------------- timestamps

def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if value is None:
        return None
    v = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond // 1000
    )


def parse_dt(raw):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ------------------------------------------------------------- common fields

def _bumped_rows():
    """Ids already counted as mutated during the current request.

    PRD 2.4 gives a row one `version` increment per mutation, and a single API
    operation mutates a given row once however many internal recomputations
    touch it -- "every row touched by any hop or by the fan-out has its
    `updated_at` refreshed and its `version` incremented", once.
    """
    try:
        from flask import g, has_request_context
        if not has_request_context():
            return None
        seen = getattr(g, "_bumped_rows", None)
        if seen is None:
            seen = set()
            g._bumped_rows = seen
        return seen
    except Exception:
        return None


def new_row(**fields):
    instant = now()
    row = {
        "id": new_id(),
        "created_at": instant,
        "updated_at": instant,
        "version": 1,
    }
    row.update(fields)
    row["_seq"] = store.next_seq()
    seen = _bumped_rows()
    if seen is not None:
        # A row created by this request stays at version 1 even if a later
        # recomputation in the same request revisits it.
        seen.add(row["id"])
    return row


def touch(row):
    """Record a mutation: refresh updated_at and increment version."""
    row["updated_at"] = now()
    seen = _bumped_rows()
    if seen is not None:
        if row["id"] in seen:
            return row
        seen.add(row["id"])
    row["version"] = row.get("version", 1) + 1
    return row


def set_fields(row, **fields):
    """Compare-and-set. Bumps version/updated_at only when something changed."""
    changed = False
    for key, value in fields.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def ordered(rows):
    """PRD 2.3: every collection is ordered by created_at ascending (creation
    order breaks ties, since the logical clock can stand still)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
