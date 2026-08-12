"""In-memory data store + logical clock. Fresh and empty on every process boot."""
import itertools
from datetime import datetime, timezone

COLLECTIONS = [
    "product_models",
    "fabric_specs",
    "dealers",
    "orders",
    "order_lines",
    "material_lots",
    "allocations",
    "cut_plans",
    "cells",
    "cell_bookings",
    "certificates",
    "requisitions",
    "samples",
    "shipments",
]


class Store:
    def __init__(self):
        self.seq = itertools.count(1)
        # Logical clock: fixed at the startup default until explicitly set.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        for name in COLLECTIONS:
            setattr(self, name, {})


store = Store()
