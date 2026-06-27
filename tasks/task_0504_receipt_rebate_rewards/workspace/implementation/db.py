"""In-memory data store. Every collection starts EMPTY on every boot — nothing is
seeded, preloaded, or hardcoded. All entities are constructed by callers via the
declared API surface.

Storage is plain Python dicts keyed by id, so a fresh process wipes all state.
"""
import itertools
import uuid

from clock import Clock, format_iso


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.merchants = {}
        self.offers = {}
        self.members = {}
        self.clickthroughs = {}
        self.receipt_scans = {}
        self.reward_claims = {}
        self.cashouts = {}
        self.referrals = {}
        self.bonus_streaks = {}      # keyed by id; one per member
        self.bonus_streak_by_member = {}  # member_id -> BonusStreak id
        self.ledger_entries = {}
        self.return_events = {}

        # Monotonic sequence to break created_at ties deterministically.
        self._seq = itertools.count(1)
        self.clock = Clock()

    def next_seq(self):
        return next(self._seq)

    def new_id(self):
        return str(uuid.uuid4())


def new_uuid():
    return str(uuid.uuid4())


def base_common_fields(store, full=True):
    """Return a dict of the system common fields for a freshly created entity.

    full=True  -> id, created_at, updated_at, version (most entities)
    full=False -> id, created_at only (append-only: ClickThrough, LedgerEntry,
                  ReturnEvent)
    """
    now_iso = format_iso(store.clock.get())
    seq = store.next_seq()
    if full:
        return {
            "id": store.new_id(),
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
            "_seq": seq,
        }
    return {
        "id": store.new_id(),
        "created_at": now_iso,
        "_seq": seq,
    }


def touch(store, entity):
    """Bump version and updated_at on a mutable entity (PRD §2.7)."""
    if "version" in entity:
        entity["version"] += 1
    if "updated_at" in entity:
        entity["updated_at"] = format_iso(store.clock.get())
