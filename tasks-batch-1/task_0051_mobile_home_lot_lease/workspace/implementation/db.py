import uuid
from response import iso_ms, now_dt


class DB:
    """In-memory data store. Starts EMPTY on every process boot.

    Every entity any test needs is constructed by the test via the declared API
    surface; nothing is seeded, preloaded, or hardcoded here.

    Entities are stored as plain dicts keyed by id, in separate collections.
    Python 3.7+ preserves dict insertion order, which we use (via _seq) as a
    stable tiebreak when created_at timestamps collide.

    `current_clock` holds the server's notion of "now" for the time-gated
    eviction cure/adjudication checks (PRD §2.9 / §3.7). It is set via
    POST /_clock/set_current_utc and starts as None (meaning "use wall clock")
    on every boot.
    """

    def __init__(self):
        self.communities = {}
        self.lots = {}
        self.residents = {}
        self.lot_leases = {}
        self.rent_schedules = {}
        self.utility_bills = {}
        self.utility_readings = {}
        self.utility_charges = {}
        self.eviction_cases = {}
        self.conversion_votes = {}
        self.conversion_ballots = {}
        self.lot_ledger_entries = {}
        self.current_clock = None  # ISO 8601 string set by the test clock
        self._seq = 0  # monotonic insertion counter for stable ordering

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def now_iso():
    return iso_ms(now_dt())


def new_common():
    """Build the common server-managed fields for a freshly created primary
    entity. The eight primary entities carry id/created_at/updated_at/version
    (PRD §2.4). version starts at 1 and increments on every mutation."""
    ts = now_iso()
    return {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def new_record():
    """Build the minimal fields for an append-only / immutable record:
    UtilityReading, UtilityCharge, ConversionBallot, LotLedgerEntry carry only
    id and created_at — no updated_at, no version (PRD §2.4)."""
    return {
        "id": db.new_id(),
        "created_at": now_iso(),
        "_seq": db.next_seq(),
    }


def touch(rec):
    """Bump updated_at and version on a mutation (PRD §2.4 / §2.9)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
