"""In-memory data store. Starts completely empty on every boot except for the
logical clock, which starts at exactly 2026-08-01T00:00:00Z (PRD section 2.5).
No entity seeding of any kind happens here."""
import uuid
from datetime import datetime, timezone

from util import fmt_ts


class Store:
    def __init__(self):
        # Logical clock — never the wall clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0  # global insertion counter (stable tie-break for sorts)
        self.practice_groups = {}
        self.providers = {}
        self.payers = {}
        self.caqh_profiles = {}
        self.applications = {}
        self.records = {}
        self.agreements = {}
        self.roster_files = {}
        self.roster_lines = {}
        self.claims = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def base_fields():
    """Common system-managed properties: id, created_at, updated_at, version."""
    ts = fmt_ts(store.clock)
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(entity):
    """Every mutation refreshes updated_at and increments version."""
    entity["updated_at"] = fmt_ts(store.clock)
    entity["version"] += 1
