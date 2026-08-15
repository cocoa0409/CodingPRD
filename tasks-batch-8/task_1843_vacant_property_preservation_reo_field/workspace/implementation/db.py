"""In-memory data store + logical clock. Store starts empty on every boot."""

import uuid
from datetime import datetime, timezone


DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def iso3(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_clock(dt):
    """Normalized clock echo: whole seconds render without fractional part."""
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return iso3(dt)


class Store:
    def __init__(self):
        self.servicers = {}
        self.crews = {}
        self.allowables = {}
        # allowable_id -> {version: snapshot of the 4 fiscal params at that version}
        self.allowable_history = {}
        self.properties = {}
        self.work_orders = {}
        self.inspections = {}
        self.dispositions = {}
        self.plans = {}
        self.violations = {}
        self.registrations = {}
        self.damage_reports = {}
        self.bids = {}
        self.photos = {}
        self.invoices = {}
        self.expense_lines = {}
        self.seq = 0
        self.clock = DEFAULT_CLOCK


store = Store()


def new_entity(fields):
    """Create an entity dict with common system fields. Does not insert."""
    store.seq += 1
    now = iso3(store.clock)
    e = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.seq,
    }
    e.update(fields)
    return e


def bump(e):
    """Increment version and refresh updated_at (single mutation batch)."""
    store.seq += 1
    e["version"] += 1
    e["updated_at"] = iso3(store.clock)
    e["_seq"] = store.seq


def bump_if_changed(e, changes):
    """Apply field changes; bump only if any value actually changed."""
    changed = False
    for k, v in changes.items():
        if e.get(k) != v:
            e[k] = v
            changed = True
    if changed:
        bump(e)
    return changed


def public(e):
    """Strip internal keys for serialization."""
    return {k: v for k, v in e.items() if not k.startswith("_")}


def clock_now():
    return store.clock


def clock_date():
    return store.clock.date()
