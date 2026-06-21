"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.facilities = {}
        self.locker_units = {}
        self.mailbox_units = {}
        self.customers = {}
        self.forms_1583 = {}
        self.authorized_recipients = {}
        self.rental_agreements = {}
        self.packages = {}
        self.mail_items = {}
        self.forwarding_requests = {}
        self.invoices = {}
        self.ledger_entries = {}
        self.payments = {}
        # Monotonic sequence to provide a stable insertion order for created_at
        # ties (created_at is real wall clock, but several rows can share a ms).
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Real wall-clock ISO 8601 UTC with 3 fractional digits (audit fields)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
