"""In-memory data store (PRD §2.4). No persistence — wiped on every boot.

Every entity carries id (server-minted UUID, no type prefix), created_at,
updated_at (ISO 8601 UTC, three fractional digits), and version (integer
starting at 1, +1 on every mutation). Timestamps are stamped from the WALL CLOCK
of resource lifecycle? No — created_at/updated_at are administrative system
fields. The PRD ties domain timestamps (recording_ended_at, published_at, etc.)
to the logical clock; created_at/updated_at are common system fields. We stamp
created_at/updated_at from the logical clock too, so that ordering (e.g. retainer
tie-break by created_at) is deterministic under the logical clock.
"""
import itertools
import uuid

from clock import clock
from timeutil import format_iso8601

# Monotonic sequence for stable insertion ordering / created_at tie-breaks when
# two records share the same logical-clock instant.
_seq = itertools.count(1)


class Store:
    """A single entity collection keyed by id."""

    def __init__(self):
        self.items = {}

    def create(self, fields):
        rid = str(uuid.uuid4())  # canonical UUID (RFC 4122), no type prefix
        now = clock.now()
        rec = {
            "id": rid,
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": next(_seq),
        }
        rec.update(fields)
        self.items[rid] = rec
        return rec

    def get(self, rid):
        return self.items.get(rid)

    def all(self):
        return list(self.items.values())

    @staticmethod
    def touch(rec):
        """Record a mutation: refresh updated_at and bump version (PRD §2.4)."""
        rec["updated_at"] = clock.now()
        rec["version"] = rec["version"] + 1


class Database:
    def __init__(self):
        self.shows = Store()
        self.contracts = Store()
        self.retainer_cycles = Store()
        self.episodes = Store()
        self.sessions = Store()
        self.engineers = Store()
        self.deliverables = Store()
        self.asset_versions = Store()
        self.invoices = Store()
        self.ad_campaigns = Store()
        self.ad_slots = Store()


db = Database()
