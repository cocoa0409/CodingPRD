"""In-memory data store. Empty on every boot; no seeding."""

import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # entity tables
        self.stations = {}
        self.carriers = {}
        self.courier_services = {}
        self.repair_vendors = {}
        self.passengers = {}
        self.bag_tags = {}
        self.reports = {}
        self.tracing_events = {}
        self.dispatches = {}
        self.repair_orders = {}
        self.expense_claims = {}
        self.settlement_payments = {}
        # unique-index helpers
        self.station_code_index = {}
        self.carrier_code_index = {}
        self.passenger_email_index = {}
        self.tag_number_index = {}
        self.report_reference_index = {}
        # logical clock (ISO-8601 UTC, milliseconds precision)
        self.current_utc_ms = None  # set at startup by app


STORE = Store()
