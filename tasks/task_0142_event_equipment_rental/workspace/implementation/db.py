"""In-memory data store. Starts empty on every boot. No seeding.

Per-test-server isolation: every test invokes `bash start.sh`, which spawns a
fresh Python process; this module is re-imported and `store` is reconstructed
empty. No file persistence anywhere.
"""
import uuid
from datetime import datetime, timezone


def utc_now_iso() -> str:
    """ISO 8601 UTC with millisecond precision (3 fractional digits), e.g.
    2025-05-24T10:30:00.123Z (PRD §2.4).
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_id() -> str:
    """Server-minted UUID, identity only, no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


class Store:
    """Pure in-memory dict store keyed by id."""

    def __init__(self):
        self.catalog_items = {}          # id -> CatalogItem
        self.customers = {}              # id -> Customer
        self.venues = {}                 # id -> Venue
        self.certificates = {}           # id -> InsuranceCertificate
        self.orders = {}                 # id -> RentalOrder
        self.order_lines = {}            # id -> OrderLine
        self.delivery_runs = {}          # id -> DeliveryRun
        self.crews = {}                  # id -> Crew
        self.ledger_entries = {}         # id -> DepositLedgerEntry (append-only)
        self.weather_events = {}         # id -> WeatherEvent (append-only)
        # Monotonic creation counter so that records minted within the same
        # millisecond still have a deterministic insertion order for list
        # endpoints (created_at ASC; the visible created_at retains ms only).
        self._seq = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq


# Module-level singleton (per process). Re-created on every process boot.
store = Store()
