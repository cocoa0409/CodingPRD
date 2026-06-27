"""In-memory data store (PRD §2.4, §2.5). All state lives in module-level dicts
keyed by id; NOTHING is seeded at startup. The logical clock starts at exactly
2026-01-01T00:00:00Z."""
import uuid
from datetime import datetime, timezone

# ---- Logical clock (PRD §2.5, §3.11) ---------------------------------------
CLOCK_START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.accounts = {}
        self.securities = {}
        self.deposits = {}
        self.orders = {}
        self.fills = {}
        self.settlements = {}
        self.positions = {}
        self.lots = {}
        self.disposals = {}
        self.dividends = {}
        self.options_approvals = {}
        self.margin_calls = {}
        # logical clock (a tz-aware datetime)
        self.clock = CLOCK_START
        # monotonic sequence so created_at ties have a deterministic ordering
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def clock_iso():
    dt = db.clock
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def created_ts():
    """A timestamp string based on the logical clock for created_at/acquired_at."""
    return clock_iso()
