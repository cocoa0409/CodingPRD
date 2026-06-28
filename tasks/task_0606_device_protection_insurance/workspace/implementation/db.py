"""In-memory data store. Starts empty on every boot. No seeding."""
import uuid

from clock import clock, to_iso


class DB:
    def __init__(self):
        self.customers = {}
        self.plans = {}
        self.replacement_skus = {}
        self.enrollments = {}
        self.premium_invoices = {}
        self.claims = {}
        self.fraud_screens = {}
        self.repair_orders = {}
        self.advanced_exchanges = {}
        self.trade_ins = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def new_id():
    return str(uuid.uuid4())


def now_logical_iso():
    return to_iso(clock.now())
