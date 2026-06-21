"""In-memory data store (PRD §2.4).

The store starts EMPTY on every process boot. No seeding, no preload. Every
entity any test needs is constructed via the declared API surface.

Each collection is an ordered dict keyed by string UUID. Insertion order is the
default sort order (creation order), which matches "sorted by created_at asc".
"""
import uuid
import itertools

# A monotonic per-process counter used only as a stable tiebreaker for ordering
# entities created at the same logical-clock instant.
_seq = itertools.count(1)


class DB:
    def __init__(self):
        self.venues = {}
        self.promoters = {}
        self.guest_list = {}
        self.reservations = {}
        self.tabs = {}
        self.tab_items = {}
        self.entries = {}
        self.id_checks = {}
        self.incidents = {}

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(_seq)


db = DB()
