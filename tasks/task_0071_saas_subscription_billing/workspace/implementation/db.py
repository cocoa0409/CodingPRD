"""In-memory data store."""
import uuid
from clock import clock, iso


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return iso(clock.now())


class Store:
    def __init__(self):
        self.tenants = {}             # id -> Tenant dict
        self.package_versions = {}    # id -> PackageVersion
        self.subscriptions = {}       # id -> Subscription
        self.subscription_changes = {}  # id -> SubscriptionChange
        self.usage_records = {}       # id -> UsageRecord
        self.invoices = {}            # id -> Invoice
        self.payments = {}            # id -> Payment
        self.credit_notes = {}        # id -> CreditNote
        self.jurisdictions = {}       # id -> Jurisdiction
        self.sync_events = {}         # id -> SyncEvent
        self.audit_logs = {}          # id -> AuditLog
        # Tracking auxiliary state:
        # suspension start timestamps (tenant_id -> ISO timestamp when SUSPENDED)
        self.suspension_started = {}
        # last dunning-step bookkeeping per invoice (e.g. tracking transitions)
        # not strictly needed; we recompute on each pass.

    # --- helpers ---
    def jurisdiction_by_code(self, code: str):
        for j in self.jurisdictions.values():
            if j["jurisdiction_code"] == code:
                return j
        return None


store = Store()
