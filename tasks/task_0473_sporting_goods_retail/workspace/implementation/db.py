"""In-memory data store for the Sporting Goods Retail API.

The store starts EMPTY on every process boot. No entity seeding occurs at
startup; every entity a test needs is constructed via the declared API surface.
State is wiped whenever the process is relaunched (per-test-server isolation).
"""

import itertools
import uuid

from clock import clock, format_iso8601_ms


class Store:
    def __init__(self):
        self.skus = {}
        self.stores = {}
        self.store_inventory = {}
        self.customers = {}
        self.orders = {}
        self.order_lines = {}
        self.service_tickets = {}
        self.fishing_licenses = {}
        self.price_match_claims = {}
        self.markdowns = {}
        self.team_orders = {}
        self.team_order_lines = {}
        # Monotonic sequence used as a deterministic creation-order tiebreaker
        # (created_at granularity is milliseconds; sequence disambiguates ties).
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    def reset(self):
        self.__init__()


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_ts():
    """Creation/mutation timestamps are stamped from the logical clock so that
    list ordering by created_at is deterministic and clock-driven."""
    return format_iso8601_ms(clock.now())
