"""In-memory data store. All state lives only in this process; every boot starts
empty. Storage is plain dicts keyed by id -- no disk, no external persistence."""
import threading
import uuid
from datetime import datetime, timezone

# Global request lock (the Flask server runs threaded; mutations stay atomic).
LOCK = threading.RLock()

contractor_accounts = {}
job_accounts = {}
jurisdictions = {}
voc_rules = {}
products = {}
tint_formulas = {}
color_match_requests = {}
product_bulletins = {}
spec_sheets = {}
spec_lines = {}
orders = {}
order_lines = {}
return_records = {}
deliveries = {}
rebate_statements = {}
loyalty_transactions = {}
mistint_listings = {}

_seq = 0
# Logical clock. Startup default is exactly 2026-05-01T00:00:00Z and the server
# never falls back to wall-clock time.
_clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def new_id():
    return str(uuid.uuid4())


def next_seq():
    """Monotonic insertion counter used as a stable sort tiebreaker (never an id)."""
    global _seq
    _seq += 1
    return _seq
