"""In-memory data store. The store starts empty on every boot: no seeding,
no preloading, no hardcoded entities. Entity timestamps read the logical
clock (PRD 2.4/2.5); a monotonically increasing sequence number gives stable
created_at ordering and 'latest' resolution within one clock instant."""

import uuid

from clock import LogicalClock

clock = LogicalClock()


class Store:
    def __init__(self):
        self.seq = 0
        self.home_models = {}
        self.communities = {}
        self.lots = {}
        self.customers = {}
        self.home_units = {}
        self.sales_orders = {}
        self.order_options = {}
        self.site_evaluations = {}
        self.financing_applications = {}
        self.transport_crews = {}
        self.transport_jobs = {}
        self.title_records = {}
        self.warranty_claims = {}
        self.trade_in_appraisals = {}
        self.delay_notices = {}


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def now():
    return clock.now()


def create_record(table, fields):
    ts = now()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(fields)
    table[rec["id"]] = rec
    return rec


def bump(rec):
    """Every mutation increments version by exactly 1 and refreshes updated_at."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = now()
