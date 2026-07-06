"""In-memory data store. Wiped on every fresh process. No seeding at startup."""
import uuid

from clock import clock


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC, three fractional digits, Z suffix."""
    # dt is timezone-aware UTC
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    micros = dt.microsecond
    millis = micros // 1000
    return f"{s}.{millis:03d}Z"


class Store:
    def __init__(self):
        self.plans = {}
        self.memberships = {}
        self.household_cards = {}
        self.products = {}
        self.instant_savings = {}
        self.transactions = {}
        self.transaction_lines = {}
        self.reward_ledger = {}
        self.returns = {}
        self.fee_events = {}
        self.payments = {}

    def stamp_created(self, obj):
        obj["created_at"] = iso(clock.get())
        return obj

    def stamp_common(self, obj):
        """id, created_at, updated_at, version for mutation-tracked entities."""
        now = iso(clock.get())
        obj["id"] = new_id()
        obj["created_at"] = now
        obj["updated_at"] = now
        obj["version"] = 1
        return obj

    def stamp_config(self, obj):
        """id, created_at only (no updated_at/version)."""
        obj["id"] = new_id()
        obj["created_at"] = iso(clock.get())
        return obj

    def touch(self, obj):
        """Refresh updated_at and bump version on a mutation-tracked entity."""
        obj["updated_at"] = iso(clock.get())
        obj["version"] += 1


db = Store()
