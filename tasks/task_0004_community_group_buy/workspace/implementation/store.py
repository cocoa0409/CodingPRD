"""In-memory data store and ID/period generation."""
import threading
import uuid
from envelope import iso_now


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.system_period_index = 0
        self._global_seq = 0
        self.communities = {}
        self.group_leaders = {}
        self.customers = {}
        self.suppliers = {}
        self.warehouses = {}
        self.flash_campaigns = {}
        self.group_buy_campaigns = {}
        self.orders = {}
        self.shipments = {}
        self.pickup_points = {}
        self.consolidation_batches = {}
        self.after_sales_cases = {}
        self.commission_entries = {}
        self.payouts = {}
        self.risk_alerts = {}
        # Auxiliary
        self.leader_clawback = {}     # leader_id -> recovered_clawback_cents
        self.flash_request_seq = {}   # flash_campaign_id -> int
        self.refund_pending = {}      # order_id -> amount waiting for sweep
        self.picked_up_period = {}    # order_id -> period when -> PICKED_UP
        self.failed_close_period = {} # campaign_id -> period when -> FAILED

    def reset(self):
        self.__init__()

    def next_seq(self):
        self._global_seq += 1
        return self._global_seq


store = Store()


def new_id():
    return str(uuid.uuid4())


def now_period():
    return store.system_period_index


def stamp_create():
    """Common-fields stamp for new mutable resources."""
    ts = iso_now()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def stamp_create_minimal():
    """Stamp for ConsolidationBatch / RiskAlert (id + created_at only)."""
    return {"id": new_id(), "created_at": iso_now()}


def bump(resource):
    """Refresh updated_at and increment version on a mutation."""
    resource["updated_at"] = iso_now()
    resource["version"] = resource.get("version", 0) + 1
