"""In-memory data store.  Starts empty on every boot; nothing is ever seeded."""
import itertools
import threading
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "yards",
    "loadout_bays",
    "consignors",
    "consignments",
    "lots",
    "condition_reports",
    "refurbishment_orders",
    "auctions",
    "bidders",
    "bidder_registrations",
    "bids",
    "sales",
    "invoices",
    "payments",
    "export_packets",
    "loadout_slots",
    "consignor_settlements",
)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)
        self.current_utc = DEFAULT_CLOCK

    # ---- clock -------------------------------------------------------
    def now(self):
        """The logical clock used for every domain timestamp (PRD 2.4)."""
        return self.current_utc

    @staticmethod
    def wall():
        """Real wall clock, used only for created_at / updated_at bookkeeping."""
        return datetime.now(timezone.utc)

    # ---- helpers -----------------------------------------------------
    def next_seq(self):
        return next(self._seq)

    def new_id(self):
        return str(uuid.uuid4())


db = Store()


def new_entity(versioned=True):
    """Common fields (PRD 2.5).  `versioned=False` for Bid / Payment."""
    stamp = db.wall()
    row = {"id": db.new_id(), "created_at": stamp}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Register a mutation: refresh updated_at and bump version."""
    if "version" in row:
        row["updated_at"] = db.wall()
        row["version"] = row["version"] + 1
    return row


def ordered(rows):
    """Default collection ordering: created_at ascending (stable by insertion)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
