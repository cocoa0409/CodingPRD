"""In-memory data store. Starts completely empty on every boot: no seeding."""

import threading
import uuid
from datetime import datetime, timezone

# PRD §2.8 — the logical shop clock reads exactly this instant until it is moved.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.skus = {}
        self.lots = {}
        self.furnaces = {}
        self.campaigns = {}
        self.chambers = {}
        self.runs = {}
        self.packs = {}
        self.pack_members = {}
        self.programs = {}
        self.claimants = {}
        self.claims = {}
        self.claim_lines = {}
        self.reports = {}
        self.clock = INITIAL_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock


store = Store()


def new_id():
    return str(uuid.uuid4())


def order_key(row):
    """Canonical ordering: created_at ascending, insertion order as tiebreaker."""
    return (row["created_at"], row["_seq"])


def sorted_rows(rows):
    return sorted(rows, key=order_key)


def base_row(**fields):
    row = {"id": new_id(), "_seq": store.next_seq()}
    now = store.now()
    row["created_at"] = now
    row.update(fields)
    return row


def with_common(row):
    """Add updated_at / version to a row that carries the common field set."""
    row["updated_at"] = row["created_at"]
    row["version"] = 1
    return row


def touch(row):
    row["updated_at"] = store.now()
    row["version"] = row.get("version", 0) + 1
