"""In-memory data store. Everything lives in process memory and is wiped on
every fresh boot (start.sh re-launch). No seeding, no persistence."""
import itertools
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


_seq = itertools.count(1)


def next_seq():
    """Monotonic insertion sequence to make created_at ordering total and stable
    even when wall-clock timestamps collide at sub-ms resolution."""
    return next(_seq)


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class DB:
    def __init__(self):
        self.departments = {}
        self.products = {}
        self.inventory_lots = {}
        self.shipments = {}
        self.shipment_lines = {}
        self.price_plans = {}
        self.promotions = {}
        self.members = {}
        self.coupons = {}
        self.clipped_coupons = {}
        self.sales = {}
        self.sale_line_items = {}
        self.cycle_counts = {}
        self.eod_reconciliations = {}


db = DB()
