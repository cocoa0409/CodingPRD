"""In-memory data store. Starts EMPTY on every boot — no seeding of any kind.
Records are plain dicts; internal keys (created_dt, updated_dt, _ord) are
rendered to created_at/updated_at by the serializers."""
import itertools
import uuid
from datetime import timedelta

from clock import now_dt


class Store:
    def __init__(self):
        self.plans = {}            # SubscriptionPlan
        self.subscribers = {}      # Subscriber
        self.subscriptions = {}    # Subscription
        self.routes = {}           # DeliveryRoute
        self.carriers = {}         # Carrier
        self.assignments = {}      # RouteAssignment
        self.holds = {}            # VacationHold
        self.complaints = {}       # DeliveryComplaint
        self.credit_memos = {}     # CreditMemo
        self.save_offers = {}      # SaveOffer
        self.racks = {}            # RackLocation
        self.rack_reports = {}     # RackSalesReport
        self.payments = {}         # Payment
        self.charges = {}          # BillingCharge
        self.audits = {}           # AuditReport


store = Store()

_ord_counter = itertools.count(1)
_ts_counter = itertools.count(1)


def _now():
    # Millisecond jitter keeps created_at strictly increasing per append even
    # when the logical clock does not advance between writes.
    return now_dt() + timedelta(milliseconds=next(_ts_counter) % 1000)


def new_id():
    return str(uuid.uuid4())


def create_rec(collection, fields):
    """Every primary resource: server-minted UUID id, created_at/updated_at,
    version starting at 1."""
    rec = dict(fields)
    rec["id"] = new_id()
    rec["_ord"] = next(_ord_counter)
    ts = _now()
    rec["created_dt"] = ts
    rec["updated_dt"] = ts
    rec["version"] = 1
    collection[rec["id"]] = rec
    return rec


def bump(rec):
    """Every mutation of a record increments version by exactly one and
    refreshes updated_at (PRD 2.4 — including system-driven mutations)."""
    rec["version"] += 1
    rec["updated_dt"] = _now()


def by_created(records):
    """created_at ASC ordering used by all list endpoints unless overridden."""
    return sorted(records, key=lambda r: (r["created_dt"], r["_ord"]))
