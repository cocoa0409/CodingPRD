"""In-memory data store. Starts empty on every boot. No seeding."""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.members = {}
        self.savings_accounts = {}
        self.linked_accounts = {}
        self.recurring_charges = {}
        self.subscriptions = {}
        self.negotiation_cases = {}
        self.concierge_agents = {}
        self.refund_claims = {}
        self.ledger_entries = {}
        # Logical clock; default per spec, never wall-clock.
        self.clock_current_utc = "2026-01-01T00:00:00Z"


db = Store()
