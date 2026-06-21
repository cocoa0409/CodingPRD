import uuid
from clock import clock
from response import iso_ms


class DB:
    """In-memory data store. Starts empty on every process boot.

    Entities are stored as plain dicts keyed by id, in separate collections.
    Insertion order is preserved (Python 3.7+ dict ordering), which we use as a
    tiebreak when created_at timestamps collide.
    """

    def __init__(self):
        self.products = {}
        self.cashback_categories = {}
        self.quarterly_categories = {}
        self.transfer_partners = {}
        self.accounts = {}
        self.transactions = {}
        self.points_lots = {}
        self.redemptions = {}
        self.category_activations = {}
        self._seq = 0  # monotonic insertion counter for stable ordering

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def now_iso():
    return iso_ms(clock.now())


def new_common(with_version=True):
    """Build the common server-managed fields for a freshly created entity.

    All entities except PointsLot carry id/created_at/updated_at/version.
    PointsLot carries only id/created_at (with_version=False).
    """
    ts = now_iso()
    rec = {
        "id": db.new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump updated_at and version on a mutation (PRD §2.4 / §2.8)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
