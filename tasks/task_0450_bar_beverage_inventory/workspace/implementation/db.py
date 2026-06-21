"""In-memory data store (SCAFFOLD: storage is in-memory only).

Every collection is a plain dict keyed by UUID id. The store is created fresh
on import, so a new process boot starts completely empty — no seeding, no
preload, no disk persistence. Tests build all state via the API surface.

Ordering: each entity records a monotonically-increasing `_seq` at creation so
list endpoints can sort by creation order (ties on created_at timestamps from
the logical clock are broken by insertion order, matching "sorted by created_at
ascending" in PRD §2.3).
"""
import itertools
import uuid

from clock import now_iso


class DB:
    def __init__(self):
        self.products = {}
        self.par_settings = {}
        self.recipes = {}
        self.recipe_lines = {}
        self.menu_items = {}
        self.count_sessions = {}
        self.count_lines = {}
        self.purchase_orders = {}
        self.po_lines = {}
        self.invoices = {}
        self.invoice_lines = {}
        self.waste_logs = {}
        self.keg_taps = {}
        self._seq = itertools.count(1)

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)


db = DB()


def stamp_create(record):
    """Set common fields on creation (PRD §2.4): id, created_at, updated_at,
    version (starts at 1), and an internal _seq for stable creation ordering."""
    ts = now_iso()
    record.setdefault("id", db.new_id())
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """A mutation refreshes updated_at and increments version by exactly 1
    (PRD §2.4). Derived-field recomputations are mutations too."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record
