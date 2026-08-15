"""In-memory data store. The store starts empty on every boot — no seeding."""
import itertools
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = itertools.count(1)
        # Logical clock: starts exactly at 2026-08-01T00:00:00Z, never falls
        # back to wall-clock time; advanced only via POST /grow/_clock/set_current_utc.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.customers = {}
        self.varieties = {}
        self.trials = {}
        self.seed_lots = {}
        self.germination_tests = {}
        self.crop_plans = {}
        self.tray_batches = {}
        self.food_safety_plans = {}
        self.sanitation_logs = {}
        self.standing_orders = {}
        self.order_items = {}
        self.delivery_routes = {}
        self.delivery_stops = {}
        self.spoilage_credits = {}
        self.surplus_listings = {}


db = Store()
