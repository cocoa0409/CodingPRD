"""In-memory data store. Starts empty on every boot; no entity seeding.

The only pre-created record is the WarehousePosition singleton, which is a
derived read model (not a business entity) — it must exist so that
GET /roastery/warehouse-position returns a zeroed position before any lot
is received.
"""

import threading
import uuid

CLOCK_DEFAULT = "2026-08-01T00:00:00Z"


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.counterparties = {}
        self.contracts = {}
        self.price_fixes = {}
        self.shipments = {}
        self.green_lots = {}
        self.financing_lines = {}
        self.financing_reserves = {}
        self.roast_profiles = {}
        self.products = {}
        self.recipes = {}
        self.recipe_components = {}
        self.roast_batches = {}
        self.roast_allocations = {}
        self.finished_goods_lots = {}
        self.cupping_sessions = {}
        self.fulfillment_orders = {}
        self.fulfillment_lines = {}
        self.futures_hedges = {}
        # Logical clock; ISO 8601 UTC string. Startup default per PRD §2.11.
        self.clock = CLOCK_DEFAULT
        # Global monotonic creation counter (tiebreak for created_at ordering
        # while the logical clock is frozen).
        self.seq = 0
        # Derived warehouse-position singleton (read model, not an entity).
        self.position = {
            "id": str(uuid.uuid4()),
            "created_at": self.clock,
            "updated_at": self.clock,
            "version": 1,
            "position_as_of": self.clock,
            "physical_lbs": 0,
            "committed_lbs": 0,
            "reserved_for_financing_lbs": 0,
            "open_to_sell_lbs": 0,
            "weighted_avg_landed_cost_usd": None,
        }

    def next_seq(self):
        self.seq += 1
        return self.seq


DB = Store()
