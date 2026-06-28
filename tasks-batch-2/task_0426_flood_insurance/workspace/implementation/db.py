"""In-memory data store for the Flood Insurance API.

The store starts EMPTY on every process boot. No entity seeding occurs at
startup; every entity a test needs is constructed via the declared API surface.
"""

import uuid

from clock import clock, format_iso8601_ms


class Store:
    def __init__(self):
        self.communities = {}
        self.properties = {}
        self.elevation_certificates = {}
        self.policies = {}
        self.claims = {}
        self.proofs_of_loss = {}
        self.policy_transfers = {}

    def reset(self):
        self.__init__()


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_ts():
    """Creation/mutation timestamps are stamped from the logical clock so that
    list ordering by created_at is deterministic and clock-driven."""
    return format_iso8601_ms(clock.now())
