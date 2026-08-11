"""In-memory data store. Fresh on every process boot; nothing is seeded."""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0  # insertion counter: stable tie-break for created_at ordering
        # Logical clock: startup default exactly 2026-05-01T00:00:00Z, never
        # falls back to wall-clock time on its own.
        self.logical_now = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.fairs = {}
        self.exhibitors = {}
        self.entries = {}
        self.weigh_tickets = {}
        self.classes = {}
        self.judges = {}
        self.ring_slots = {}
        self.placings = {}
        self.premium_awards = {}
        self.buyers = {}
        self.auction_lots = {}
        self.add_ons = {}
        self.invoices = {}
        self.dispositions = {}
        self.health_inspections = {}
        self.affidavits = {}


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def iso(dt):
    """Render an aware datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso(datetime.now(timezone.utc))


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware datetime, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith('Z') or s.endswith('z'):
        s = s[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def new_record(fields, common=True):
    """Build a new stored record with server-minted identity/audit fields."""
    rec = dict(fields)
    rec['id'] = new_id()
    rec['created_at'] = now_iso()
    if common:
        rec['updated_at'] = rec['created_at']
        rec['version'] = 1
    rec['_seq'] = next_seq()
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and advances version by one."""
    rec['version'] += 1
    rec['updated_at'] = now_iso()
