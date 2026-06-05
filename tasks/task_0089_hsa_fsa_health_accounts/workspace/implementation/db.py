import uuid
import threading
from datetime import datetime, timezone


def now_iso():
    # ISO 8601 UTC with three fractional digits, trailing Z (PRD §2.4)
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    # server-minted UUID with no type prefix (PRD §2.4)
    return str(uuid.uuid4())


class Store:
    """In-memory store. Starts empty on every boot. No seeding."""

    def __init__(self):
        self.lock = threading.RLock()
        self.participants = {}
        self.plan_years = {}
        self.accounts = {}
        self.contributions = {}
        self.claims = {}
        self.batches = {}
        self.ledger_entries = {}
        # ClockState is a singleton control record (PRD §2.4, §3.9).
        self.clock = {"current_utc": now_iso()}
        self._seq = 0

    def next_seq(self):
        # monotonic creation-order tiebreaker (created_at can collide at ms precision)
        self._seq += 1
        return self._seq


db = Store()
