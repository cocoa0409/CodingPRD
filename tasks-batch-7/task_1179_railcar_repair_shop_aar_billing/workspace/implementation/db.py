"""In-memory data store and logical clock.

All state lives only in this process's memory. Nothing is written to disk,
so every fresh `start.sh` invocation boots with an empty store.
"""
import threading
import uuid
from datetime import datetime, timezone

# Global lock serializing request handling (OCC races etc.).
LOCK = threading.RLock()

COLLECTIONS = (
    "shops",
    "car_owners",
    "handling_lines",
    "railcars",
    "inspections",
    "defects",
    "work_orders",
    "repair_lines",
    "price_entries",
    "parts",
    "wheelsets",
    "shop_slots",
    "brcs",
    "brc_lines",
    "counter_bills",
    "warranty_claims",
)

STORE = {name: {} for name in COLLECTIONS}

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


# Logical clock: exactly 2026-05-01T00:00:00Z at startup; never wall-clock.
_DEFAULT_NOW = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": _DEFAULT_NOW}


def clock_now():
    return _clock["now"]


def clock_set(dt):
    _clock["now"] = dt
