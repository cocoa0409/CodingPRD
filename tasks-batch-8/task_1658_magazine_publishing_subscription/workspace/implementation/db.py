"""In-memory data store.

All state lives in module-level Python dicts keyed by resource id. The server
is re-launched from a fresh process for every test (per-test-server
isolation), so process exit wipes every byte of state. No files, no SQLite,
no /tmp caches.

Nothing is seeded here: the store starts completely empty on every boot.
"""

from datetime import datetime, timezone

# Logical clock startup default: exactly 2026-08-01T00:00:00Z (PRD section 2.4).
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.publications = {}
        self.issues = {}
        self.subscribers = {}
        self.subscriptions = {}
        self.terms = {}
        self.renewal_series = {}
        self.renewal_events = {}
        self.batches = {}
        self.labels = {}
        self.postal_statements = {}
        self.back_issue_orders = {}
        self.entitlements = {}
        self.revenue_entries = {}
        self.audits = {}
        # Global monotonic creation counter, used as a stable tie-breaker so
        # "sorted by creation timestamp ascending" is deterministic even when
        # several resources share the same logical-clock instant.
        self.seq = 0
        self.current_utc = CLOCK_DEFAULT

    def next_seq(self):
        self.seq += 1
        return self.seq

    def now(self):
        return self.current_utc


store = Store()


def new_record(common_fields=True):
    """Base system fields for a fresh resource."""
    import uuid

    now = store.now()
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "_seq": store.next_seq(),
    }
    if common_fields:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version (exactly +1 per modification)."""
    rec["updated_at"] = store.now()
    rec["version"] += 1
