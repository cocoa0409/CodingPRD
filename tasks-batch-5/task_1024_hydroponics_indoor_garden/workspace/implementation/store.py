"""In-memory data store and helpers.

All state lives in module-level dicts keyed by id. Every process start wipes
state; nothing is seeded or persisted (PRD: tests build all state via the API).
"""
import uuid
import random
import string
from datetime import datetime, timezone, timedelta

# Logical-clock default (PRD §2.6): startup reads exactly this instant and
# never falls back to wall-clock until an admin sets it.
CLOCK_DEFAULT = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.products = {}
        self.inventory_lots = {}
        self.customers = {}
        self.commercial_accounts = {}
        self.orders = {}
        self.subscriptions = {}
        self.consultants = {}
        self.consult_bookings = {}
        self.rooms = {}
        self.workshop_sessions = {}
        self.workshop_registrations = {}
        self.rmas = {}
        self.logical_clock = CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def real_now():
    return datetime.now(timezone.utc)


def clock_now():
    return store.logical_clock


def request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def parse_iso(value):
    """Parse an ISO 8601 datetime (accepts trailing Z). Returns aware datetime
    or None on failure."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def base_fields():
    """Common system fields (PRD §2.4): id, created_at, updated_at, version.
    version starts at 1 and increments by one on every mutation."""
    now = iso(real_now())
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(entity):
    """Record a mutation: bump version and refresh updated_at."""
    entity["version"] += 1
    entity["updated_at"] = iso(real_now())


def public(entity):
    """Serialize an entity, dropping internal ('_'-prefixed) fields."""
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sort_by_created(items):
    """Deterministic list order (PRD §2.3): creation timestamp ascending, with
    insertion sequence as a stable tiebreaker."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
