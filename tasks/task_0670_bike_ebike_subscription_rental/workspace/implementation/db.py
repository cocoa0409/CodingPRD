"""In-memory data store. All state is wiped on process boot — no seeding,
no persistence. Each entity collection is a dict keyed by id."""
import threading
import uuid
from datetime import timezone


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.bike_models = {}
        self.accounts = {}
        self.rentals = {}
        self.deliveries = {}
        self.service_tickets = {}
        self.inspection_reports = {}
        self.coverage_claims = {}
        self.buyout_offers = {}
        self.fleet_invoices = {}
        self.bikes = {}
        self._seq = 0

    def new_id(self):
        # Server-minted UUID with no type prefix (PRD §2.4).
        return str(uuid.uuid4())

    def next_seq(self):
        # Monotonic insertion order tie-breaker for deterministic created_at sort.
        self._seq += 1
        return self._seq


db = DB()


def iso_ms(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
