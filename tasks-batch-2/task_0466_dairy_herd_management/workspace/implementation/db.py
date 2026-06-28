"""In-memory data store. Every byte of state is wiped on each process start.

NO seeding, preloading, or hardcoding of entities. Tests build all state via
the API surface.
"""
import threading

# One dict per entity, keyed by id.
herds = {}
parlors = {}
rations = {}
coop_price_sheets = {}
animals = {}
lactations = {}
test_day_records = {}
milking_shifts = {}
breeding_events = {}
calving_events = {}
health_treatments = {}
milk_checks = {}
cull_decisions = {}

# Monotonic creation counter so that resources created within the same
# millisecond still sort deterministically by creation order (PRD §2.3 — sort
# by created_at ascending). Stored alongside each record as "_seq".
_seq_counter = 0

# A single coarse lock to keep multi-entity cascades atomic.
lock = threading.RLock()


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter
