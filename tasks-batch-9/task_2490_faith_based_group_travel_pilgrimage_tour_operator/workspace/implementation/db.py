"""In-memory data store.

Storage is process-local Python dictionaries keyed by id.  Nothing is persisted
and nothing is seeded: the store always boots empty and every row is created by
a client through the declared endpoints.
"""

import itertools
import threading
import uuid
from datetime import datetime, timezone

# Logical clock default mandated by PRD section 2.4.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_seq_counter = itertools.count(1)


class Store:
    """Collections keyed by row id, plus the server-owned logical clock."""

    def __init__(self):
        self.programs = {}
        self.departures = {}
        self.agreements = {}
        self.pilgrims = {}
        self.payment_plans = {}
        self.payments = {}
        self.air_blocks = {}
        self.sacred_sites = {}
        self.service_bookings = {}
        self.land_resources = {}
        self.land_assignments = {}
        self.protections = {}
        self.advisories = {}
        self.clock = DEFAULT_CLOCK


db = Store()
lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)
