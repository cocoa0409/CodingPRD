"""In-memory data store. PRD §2.4: ids are server-minted UUIDs with no type prefix.
State is wiped on every fresh boot (module load) — NO seeding of any entity here."""
import uuid
import itertools
from datetime import timezone

from clock import clock


class Store:
    """Holds all entity collections keyed by id, plus append-only ledgers."""

    def __init__(self):
        # Mutable, common-field entities
        self.members = {}
        self.stores = {}
        self.menu_items = {}
        self.modifier_options = {}
        self.cards = {}
        self.orders = {}
        self.order_lines = {}
        self.pickup_slots = {}
        self.rewards = {}
        self.refunds = {}
        # Append-only event ledgers (id + created_at only)
        self.wallet_transactions = {}
        self.star_ledger_entries = {}
        # Monotonic sequence to break created_at ties deterministically
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def iso_now():
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.4)."""
    return iso_format(clock.now())


def iso_format(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # millisecond precision, trailing Z
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"
