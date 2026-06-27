"""In-memory data store (PRD: API correctness, no durability).

Every collection is a plain dict keyed by id. The store starts EMPTY on every
boot — nothing is seeded. The test harness re-launches start.sh before each test,
so a fresh process wipes all state.
"""
import threading
import uuid

from clock import Clock, fmt_iso

# Monotonic creation counter so created_at ties (same logical clock instant) still
# sort deterministically by insertion order (PRD §2.3 created_at ASC ordering).
_seq_lock = threading.Lock()


class Store:
    def __init__(self):
        self.accounts = {}
        self.disclosures = {}
        self.loans = {}
        self.schedules = {}          # InstallmentSchedule
        self.payments = {}
        self.secured_cards = {}
        self.card_deposits = {}
        self.autopay_enrollments = {}
        self.bureau_reports = {}
        self.score_snapshots = {}
        self.payoff_quotes = {}
        self.clock = Clock()
        self._seq = 0

    def next_seq(self):
        with _seq_lock:
            self._seq += 1
            return self._seq

    def new_id(self):
        # server-minted UUID with no type prefix (PRD §2.4)
        return str(uuid.uuid4())

    def now(self):
        return self.clock.now()

    def now_iso(self):
        return fmt_iso(self.clock.now())


# Single global store instance for the process. Created at import — EMPTY.
store = Store()


def reset():
    """Re-init the store (used only for a clean process; not seeding)."""
    global store
    store = Store()
