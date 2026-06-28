"""In-memory data store.

The store starts empty on every boot. No seeding, no preloading. Tests build all
preconditions via the declared API surface.

System-managed fields (PRD §2.4):
  Versioned resources (Host, Driver, Spot, PricingEvent, Booking, ViolationRecord,
  TransferOffer) carry: id (UUID), created_at, updated_at, version (starts at 1).
  Lightweight resources (AccessPass, PayoutLedgerEntry) carry only id + created_at.
"""
import itertools
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def _iso_ts():
    # Stored timestamps: ISO 8601 UTC with three fractional digits.
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.hosts = {}
        self.drivers = {}
        self.spots = {}
        self.pricing_events = {}
        self.bookings = {}
        self.access_passes = {}
        self.violations = {}
        self.ledger_entries = {}
        self.transfer_offers = {}
        # Monotonic creation sequence to give a stable tiebreak for equal-millisecond
        # created_at values (used for ascending sort and tie-breaks like surge selection
        # and confirmed-violation ordering).
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def make_versioned(fields):
    """Attach system fields for a versioned resource and return the record dict."""
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = _iso_ts()
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def make_lightweight(fields):
    """Attach system fields for an append-only resource (AccessPass, ledger entry)."""
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = _iso_ts()
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Mark a versioned resource mutated: refresh updated_at and bump version."""
    rec["updated_at"] = _iso_ts()
    rec["version"] = rec["version"] + 1
