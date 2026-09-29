"""In-memory store, logical clock and mutation bookkeeping.

The store is empty on every process boot: nothing is seeded, preloaded or
hardcoded. Every row is created by a client through the declared API surface.
"""
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone

import constants

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso8601(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, off = m.groups()
    try:
        micro = 0
        if frac:
            micro = int(round(float(frac) * 1_000_000))
        dt = datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        body = off[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:]))
        dt = dt - sign * delta
    return dt


def iso_millis(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.projects = {}
        self.mix_designs = {}
        self.steam_zones = {}
        self.casting_beds = {}
        self.bed_runs = {}
        self.curing_cycles = {}
        self.cylinder_sets = {}
        self.cylinder_breaks = {}
        self.pieces = {}
        self.yard_slots = {}
        self.yard_placements = {}
        self.haul_permits = {}
        self.shipments = {}
        self.shipment_lines = {}
        self.repair_dispositions = {}
        self._seq = 0
        self.clock = parse_iso8601(constants.CLOCK_DEFAULT_ISO)

    # -- identity / ordering ------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    # -- logical clock ------------------------------------------------------
    def now(self):
        return self.clock

    def now_iso(self):
        return iso_millis(self.clock)


store = Store()


def new_row(collection, fields, versioned=True):
    """Create a row with its system-managed fields (PRD 2.5) and store it."""
    row = dict(fields)
    row["id"] = store.new_id()
    row["_seq"] = store.next_seq()
    row["created_at"] = store.now_iso()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    collection[row["id"]] = row
    return row


def touch(row):
    """Record a mutation on `row`: refresh updated_at and bump version.

    A row mutated several times while serving one request counts as one
    mutation (PRD 2.5/2.11: each row a cascade touches is mutated once).
    """
    if row is None or "version" not in row:
        return row
    from flask import g
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    key = id(row)
    if key in touched:
        return row
    touched.add(key)
    row["updated_at"] = store.now_iso()
    row["version"] = row["version"] + 1
    return row


def mark_fresh(row):
    """Exempt a row created in this request from touch() bookkeeping."""
    from flask import g
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    touched.add(id(row))
    return row


def by_seq(rows):
    """Default list order: created_at ascending (PRD 2.3), insertion-stable."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
