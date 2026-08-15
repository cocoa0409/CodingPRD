"""In-memory data store. The store starts empty on every boot; no seeding."""

import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.owner_operators = {}
        self.trucks = {}
        self.lease_agreements = {}
        self.escrow_accounts = {}
        self.settlement_statements = {}
        self.lane_assignments = {}
        self.service_bays = {}
        self.maintenance_work_orders = {}
        self.compliance_documents = {}
        self.buyout_quotes = {}


db = Store()
