"""In-memory data store.

All state lives in process memory only. start.sh re-invocation wipes everything.
Each entity collection is a dict keyed by id. A monotonically increasing seq
counter assigns a per-record creation order so that list ordering by created_at
is stable and tie-breaks are deterministic.
"""
import uuid

from clock import LogicalClock, iso_format


class Store:
    def __init__(self):
        self.clock = LogicalClock()
        self._seq = 0
        # one dict per entity type
        self.resellers = {}
        self.clients = {}
        self.site_audits = {}
        self.keyword_targets = {}
        self.rank_snapshots = {}
        self.retainers = {}
        self.contracts = {}
        self.sprints = {}
        self.deliverables = {}
        self.ad_campaigns = {}
        self.ad_spend_disputes = {}
        self.gbp_listings = {}
        self.reports = {}

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now_iso(self):
        return self.clock.now_iso()


# Single global store instance — reconstructed fresh on every process boot.
store = Store()


def base_record(versioned=True):
    """Create the common system fields for a new record.

    versioned=True -> id, created_at, updated_at, version (starts at 1)
    versioned=False -> id, created_at only (append-only/immutable records)
    """
    now = store.now_iso()
    rec = {
        "id": store.new_id(),
        "created_at": now,
        "_seq": store.next_seq(),
    }
    if versioned:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a mutation."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = store.now_iso()
