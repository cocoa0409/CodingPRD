import uuid
import threading
from datetime import datetime, timezone


def now_iso():
    # ISO 8601 UTC with three fractional digits, trailing Z
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


class Store:
    """In-memory store. Starts empty on every boot. No seeding."""

    def __init__(self):
        self.lock = threading.RLock()
        self.seasons = {}
        self.teams = {}
        self.players = {}
        self.contracts = {}
        self.stints = {}
        self.trades = {}
        self.fines = {}
        self.sponsorships = {}
        self.revenue_shares = {}
        self._seq = 0

    def next_seq(self):
        # monotonic creation order tiebreaker (created_at can collide at ms precision)
        self._seq += 1
        return self._seq


db = Store()
