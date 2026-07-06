"""In-memory data store — empty on every boot; no seeding."""
import uuid


class Store:
    def __init__(self):
        self.customers = {}
        self.plants = {}
        self.stock_units = {}
        self.care_log_entries = {}
        self.delivery_drivers = {}
        self.orders = {}
        self.order_lines = {}
        self.deliveries = {}
        self.subscriptions = {}
        self.care_reminders = {}
        self.workshops = {}
        self.workshop_registrations = {}
        self.warranty_claims = {}
        self.special_orders = {}
        self.loyalty_ledger = {}


DB = Store()


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex
