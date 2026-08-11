"""In-memory data store. Starts completely empty on every boot — no seeding."""

import uuid


def new_id():
    return str(uuid.uuid4())


class DB:
    """Container for all entity stores. Instantiated once per process."""

    def __init__(self):
        self.customers = {}
        self.products = {}
        self.area_restrictions = {}
        self.subscriptions = {}
        self.delivery_routes = {}
        self.delivery_windows = {}
        self.orders = {}
        self.order_lines = {}
        self.moisture_readings = {}
        self.invoices = {}
        self.payment_events = {}
        # Server-side bookkeeping
        self.invoice_seq = 0  # per (season_year) -> seq handled via dict below
        self.invoice_seq_by_year = {}


db = DB()
