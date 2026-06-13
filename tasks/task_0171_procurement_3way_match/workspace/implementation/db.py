"""In-memory data store, server clock, id/timestamp helpers.

Storage is purely in-process dicts keyed by id. No persistence, no seeding —
every entity is constructed by tests via the declared API surface. A fresh
process (each start.sh re-invocation) starts with an empty store.
"""
import uuid
import random
import string
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.spend_categories = {}
        self.vendors = {}
        self.requisitions = {}
        self.approval_steps = {}
        self.rfqs = {}
        self.quotes = {}
        self.purchase_orders = {}
        self.release_orders = {}
        self.goods_receipts = {}
        self.invoices = {}
        self.match_exceptions = {}
        self.vendor_scorecards = {}

        # Monotonic insertion sequence for stable created_at ordering when
        # multiple resources share the same (possibly frozen) clock instant.
        self._seq = 0

        # Server clock override (set via _clock/set_current_utc). When None the
        # real wall clock is used.
        self._frozen_now = None

    def next_seq(self):
        self._seq += 1
        return self._seq

    # --- clock ---
    def now(self):
        """Server 'now' — the frozen instant if set, else the real UTC clock."""
        if self._frozen_now is not None:
            return self._frozen_now
        return datetime.now(timezone.utc)

    def set_clock(self, dt):
        self._frozen_now = dt


db = Store()


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    """Request id starting with req_ (PRD §2.2)."""
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso(db.now())
