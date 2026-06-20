"""In-memory data store. Every byte of state lives here and is wiped on a fresh
process boot (no disk, no external persistence)."""
import uuid
from datetime import datetime, timezone


def new_id():
    # Server-minted UUID with no type prefix (PRD §2.4).
    return str(uuid.uuid4())


def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    # ISO 8601 UTC timestamp with three fractional digits (PRD §2.4).
    # Derived from the logical clock so the entire timeline (auth expiry,
    # funding maturity, reserve release, settle posting year) is reproducible
    # under operator clock control (PRD §3.12). The clock defaults to
    # wall-clock-now at boot, so unmanipulated timestamps are real time.
    return _fmt(store.clock)


class Store:
    """One dict per entity type, keyed by id."""

    def __init__(self):
        self.merchants = {}
        self.fee_plans = {}
        self.charges = {}
        self.refunds = {}
        self.disputes = {}
        self.settlement_batches = {}
        self.payouts = {}
        self.reserve_entries = {}
        self.ledger_entries = {}
        self.tax_1099k = {}
        self.risk_reviews = {}
        self.webhook_events = {}

        # monotonic insertion counter for deterministic created_at ordering
        self._seq = 0

        # Logical clock: defaults to wall-clock now at boot (PRD §3.12). Stored
        # as an aware UTC datetime; operators set/advance it.
        self.clock = datetime.now(timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq


# Single global store instance. Starts empty on every boot — NO seeding.
store = Store()
