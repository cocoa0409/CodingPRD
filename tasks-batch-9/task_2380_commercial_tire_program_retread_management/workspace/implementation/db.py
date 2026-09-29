"""In-memory data store and the logical clock (PRD §2.5).

The store is empty on every boot: nothing is seeded, preloaded or hardcoded.
"""

import threading

from util import new_id, now_iso, parse_datetime

# The logical clock reads exactly this instant until a request sets it (PRD §2.5).
DEFAULT_CLOCK_RAW = "2026-08-01T00:00:00Z"


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.service_locations = {}
        self.fleet_accounts = {}
        self.national_agreements = {}
        self.tire_policies = {}
        self.vehicles = {}
        self.casings = {}
        self.tire_assets = {}
        self.tire_surveys = {}
        self.casing_credit_entries = {}
        self.retread_lines = {}
        self.retread_jobs = {}
        self.technicians = {}
        self.road_service_calls = {}
        self.scrap_manifests = {}
        self.cross_location_invoices = {}

        self.clock_raw = DEFAULT_CLOCK_RAW
        self.clock_dt = parse_datetime(DEFAULT_CLOCK_RAW)

        self._seq = 0
        self._manifest_seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def next_manifest_number(self):
        self._manifest_seq += 1
        return "SM-%06d" % self._manifest_seq

    def clock_date(self):
        return self.clock_dt.date()


db = Store()


def insert(collection, row, versioned=True):
    """Insert a new row, stamping the common fields (PRD §2.4)."""
    row["id"] = row.get("id") or new_id()
    row["created_at"] = now_iso()
    row["_seq"] = db.next_seq()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    collection[row["id"]] = row
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly 1 (PRD §2.4, §2.10)."""
    if row is None:
        return None
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 1) + 1
    return row


def ordered(rows):
    """Default list ordering: created_at ascending (insertion order, PRD §2.3)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
