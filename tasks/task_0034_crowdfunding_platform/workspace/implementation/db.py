"""In-memory data store with global lock for serialization."""

import threading
import uuid
from datetime import timezone


# A single coarse-grained lock keeps every mutating endpoint serialized,
# which is sufficient for the concurrency guarantees described in PRD §2.11.
LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.initiators = {}
        self.backers = {}
        self.projects = {}
        self.rewards = {}
        self.add_on_items = {}
        self.orders = {}
        self.progress_updates = {}
        self.refund_requests = {}
        self.settlement_batches = {}
        self.audit_log = []
        self.escrow_ledger = []
        # Track which X-User-IDs approved which review stages on each project.
        # project_id -> {"content": user_id|None, "legal": user_id|None, "financial": user_id|None}
        self.review_decisions = {}
        # Track shipments per order: order_id -> list of {value_cents, line_id}
        self.shipments = {}
        # Track per-order pinned commission and channel fee at charge time.
        # order_id -> {"commission_cents": int, "channel_fee_cents": int, "charged_at": datetime}
        self.order_charge_pins = {}

    def reset(self):
        self.__init__()


DB = Store()


def new_id() -> str:
    return str(uuid.uuid4())


def from_iso(value):
    """Parse ISO 8601 inputs into aware UTC datetimes when needed."""
    if value is None:
        return None
    from datetime import datetime
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
