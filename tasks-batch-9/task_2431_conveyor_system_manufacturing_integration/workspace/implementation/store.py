"""In-memory data store, logical clock and shared record helpers.

Storage is process-local Python dicts keyed by id.  The store starts completely
empty on every boot: nothing is seeded, preloaded or hardcoded.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

# The logical clock's startup value (PRD section 2.4).
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = CLOCK_START
        self._seq = 0
        self.projects = {}
        self.segments = {}
        self.flow_links = {}
        self.simulation_runs = {}
        self.staging_bays = {}
        self.fabrication_lots = {}
        self.fat_tests = {}
        self.site_zones = {}
        self.cutover_windows = {}
        self.commissioning_ramps = {}
        self.acceptance_certificates = {}
        self.change_orders = {}
        self.spare_part_lines = {}
        self.performance_disputes = {}

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


# --------------------------------------------------------------------------
# clock / time helpers
# --------------------------------------------------------------------------
def now():
    """Current logical-clock instant (never the host wall clock)."""
    return store.clock


def set_clock(dt):
    store.clock = dt


def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text[-1] in ("z", "Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def plus_days(dt, days):
    return dt + timedelta(days=days)


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------
def new_record(versioned=True):
    """Base fields for a fresh record; created_at reads the logical clock."""
    instant = now()
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": iso(instant),
        "_created_dt": instant,
        "_seq": store.next_seq(),
    }
    if versioned:
        rec["updated_at"] = iso(instant)
        rec["version"] = 1
    _mark_touched(rec["id"])
    return rec


def _touched_set():
    if not hasattr(g, "touched_ids"):
        g.touched_ids = set()
    return g.touched_ids


def _mark_touched(record_id):
    try:
        _touched_set().add(record_id)
    except RuntimeError:  # outside of a request context
        pass


def touch(record):
    """Bump a record's version/updated_at once per request.

    PRD section 2.4: every mutated row independently increments its own version
    by exactly 1 and refreshes its own updated_at, no matter how many fields a
    single request changes on it.
    """
    if record is None or "version" not in record:
        return
    try:
        touched = _touched_set()
    except RuntimeError:
        touched = None
    if touched is not None:
        if record["id"] in touched:
            return
        touched.add(record["id"])
    record["version"] += 1
    record["updated_at"] = iso(now())


def sort_key(record):
    """created_at ascending; creation sequence is the stable tie-break.

    Identifiers never participate in ordering (PRD section 2.4).
    """
    return (record["_created_dt"], record["_seq"])


def ordered(records):
    return sorted(records, key=sort_key)


def public(record, fields):
    return {name: record.get(name) for name in fields}


# --------------------------------------------------------------------------
# collection queries
# --------------------------------------------------------------------------
def segments_of(project_id):
    return ordered([s for s in store.segments.values() if s["project_id"] == project_id])


def links_of(project_id):
    return ordered([l for l in store.flow_links.values() if l["project_id"] == project_id])


def runs_of(project_id):
    return ordered([r for r in store.simulation_runs.values() if r["project_id"] == project_id])


def lots_of(project_id):
    return ordered([l for l in store.fabrication_lots.values() if l["project_id"] == project_id])


def zones_of(project_id):
    return ordered([z for z in store.site_zones.values() if z["project_id"] == project_id])


def windows_of(project_id):
    return ordered([w for w in store.cutover_windows.values() if w["project_id"] == project_id])


def ramps_of(project_id):
    return ordered([r for r in store.commissioning_ramps.values() if r["project_id"] == project_id])


def change_orders_of(project_id):
    return ordered([c for c in store.change_orders.values() if c["project_id"] == project_id])


def spare_lines_of(project_id):
    return ordered([s for s in store.spare_part_lines.values() if s["project_id"] == project_id])


def certificates_of(project_id):
    return ordered(
        [c for c in store.acceptance_certificates.values() if c["project_id"] == project_id]
    )


def disputes_of(certificate_id):
    return ordered(
        [
            d
            for d in store.performance_disputes.values()
            if d["acceptance_certificate_id"] == certificate_id
        ]
    )


def fat_tests_of(lot_id):
    return ordered([t for t in store.fat_tests.values() if t["fabrication_lot_id"] == lot_id])
