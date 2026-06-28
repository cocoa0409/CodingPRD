"""In-memory data store. Wiped on every process boot (no persistence)."""
import itertools
import uuid
from datetime import datetime, timezone

# Monotonic sequence so we can break created_at ties deterministically
# (oldest-first selection of stock items relies on stable ordering).
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        # one dict per entity type, keyed by id
        self.titles = {}
        self.stock_items = {}
        self.members = {}
        self.credit_ledger = {}
        self.sales_orders = {}
        self.order_lines = {}
        self.special_orders = {}
        self.publisher_returns = {}
        self.author_events = {}
        self.event_tickets = {}
        self.buybacks = {}
        self.buyback_lines = {}
        self.consignment_agreements = {}
        self.consignment_copies = {}

    def next_seq(self):
        return next(_seq)


db = Store()
