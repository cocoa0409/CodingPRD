import uuid
from clock import clock
from response import iso_ms


class DB:
    """In-memory data store. Starts empty on every process boot.

    Entities are stored as plain dicts keyed by id, in separate collections.
    Insertion order is preserved (Python 3.7+ dict ordering); we additionally
    stamp a monotonic ``_seq`` so created_at ties resolve deterministically.

    NOTE: nothing is seeded here. Every entity a test needs is built through the
    declared API surface (PRD §3, §4).
    """

    def __init__(self):
        self.fare_products = {}
        self.riders = {}
        self.funding_sources = {}
        self.reduced_fare_cards = {}
        self.benefit_allocations = {}
        self.fare_weeks = {}
        self.taps = {}
        self._seq = 0

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def now_iso():
    return iso_ms(clock.now())


def new_common():
    """Build the common server-managed fields for a freshly created entity
    (PRD §2.4): id (bare UUID), created_at, updated_at, version=1."""
    ts = now_iso()
    return {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(rec):
    """Bump updated_at and version on a mutation (PRD §2.4)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
