"""In-memory data store. Every byte of state lives in module-level dicts and
is wiped on each process boot (start.sh re-invocation). No seeding at startup.
"""
import uuid
from datetime import datetime, timezone

from response import now_iso


class Store:
    def __init__(self):
        # One dict per entity, keyed by id.
        self.plans = {}
        self.price_schedules = {}
        self.addons = {}
        self.coupons = {}
        self.tax_jurisdictions = {}
        self.accounts = {}
        self.subscriptions = {}
        self.subscription_addons = {}
        self.pause_windows = {}
        self.usage_records = {}
        self.invoices = {}
        self.invoice_lines = {}
        self.payments = {}
        self.revenue_entries = {}
        # Simulated clock (PRD §3.9 /_clock/set). Defaults to real now.
        self._clock = datetime.now(timezone.utc)

    # ---- clock --------------------------------------------------------------
    def now(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt


db = Store()


def new_id():
    # Server-minted UUID with no type prefix (PRD §2.4).
    return str(uuid.uuid4())


def stamp_new(obj, versioned=True):
    """Set system-managed common fields on creation (PRD §2.4)."""
    ts = now_iso()
    obj["id"] = new_id()
    obj["created_at"] = ts
    if versioned:
        obj["updated_at"] = ts
        obj["version"] = 1
    return obj


def touch(obj):
    """Refresh updated_at and bump version on mutation (PRD §2.4)."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
