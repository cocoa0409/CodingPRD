"""In-memory data store. No persistence, no seeding — fresh on every boot.

Each entity collection is a dict keyed by the server-minted UUID id.
Common system fields per PRD §2.4: id, created_at, updated_at, version.
"""
import itertools
import uuid
from datetime import datetime, timezone

from response import now_iso


class Store:
    def __init__(self):
        # One dict per entity type, keyed by id. Built entirely via API calls.
        self.applicants = {}
        self.residency_verifications = {}
        self.education_certificates = {}
        self.license_products = {}
        self.species_seasons = {}
        self.draw_pools = {}
        self.draw_applications = {}
        self.licenses = {}
        self.harvest_reports = {}
        self.replacements = {}

        # Monotonic creation sequence to break created_at ties deterministically
        # (created_at has only millisecond resolution; sort uses (created_at, _seq)).
        self._seq = itertools.count(1)

        # Logical clock (PRD §2.9). None until a DrawOfficer sets it.
        self._clock_iso = None

    # ---- id / timestamp / version helpers ----
    def new_id(self):
        # Server-minted UUID with no type prefix (PRD §2.4).
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)

    def stamp_new(self, record):
        ts = now_iso()
        record["id"] = self.new_id()
        record["created_at"] = ts
        record["updated_at"] = ts
        record["version"] = 1
        record["_seq"] = self.next_seq()
        return record

    def touch(self, record):
        # A mutation: refresh updated_at and bump version (PRD §2.4).
        record["updated_at"] = now_iso()
        record["version"] = record["version"] + 1

    # ---- logical clock (PRD §2.9) ----
    def set_clock(self, iso_str):
        self._clock_iso = iso_str

    def now(self):
        # Returns a timezone-aware datetime representing the logical "now".
        if self._clock_iso is not None:
            return parse_dt(self._clock_iso)
        return datetime.now(timezone.utc)

    def now_iso(self):
        if self._clock_iso is not None:
            return self._clock_iso
        return now_iso()


def parse_dt(iso_str):
    """Parse an ISO 8601 datetime string into a tz-aware UTC datetime."""
    s = iso_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# Single global store instance, recreated each process boot (empty).
store = Store()
