"""In-memory data store. All state lives in module-level dicts keyed by id.

Storage is in-memory ONLY. A fresh process (start.sh re-invocation) wipes all
state. No seeding, no preloaded entities.
"""
import uuid
import threading
from datetime import datetime, timezone

# A global lock to keep multi-step mutations atomic under Flask's threaded server.
LOCK = threading.RLock()

# One dict per entity type, keyed by id.
customers = {}
skus = {}
tune_up_tiers = {}
service_tickets = {}
labor_lines = {}
service_bays = {}
bay_bookings = {}
sales_orders = {}
order_lines = {}
reservations = {}
layaway_plans = {}
special_orders = {}
build_jobs = {}
warranty_claims = {}
trade_ins = {}
recall_notices = {}
recall_acks = {}
payments = {}

# Monotonic sequence for stable creation ordering (sorting by created_at can tie
# when timestamps collide; this gives a deterministic tiebreak).
_seq = 0

# Server "current UTC" clock; settable via /_clock/set_current_utc for tests.
_clock_override = None


def next_seq():
    global _seq
    _seq += 1
    return _seq


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def set_clock(iso_string):
    global _clock_override
    _clock_override = iso_string


def current_utc():
    """The server clock used to anchor promised_ready_at. Overridable for tests."""
    if _clock_override is not None:
        return _parse_iso(_clock_override)
    return datetime.now(timezone.utc)


def _parse_iso(s):
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
