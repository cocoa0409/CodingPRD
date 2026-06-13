"""In-memory data store.

Every collection is a plain dict keyed by id. The store starts EMPTY on every
process boot — nothing is seeded, preloaded, or hardcoded. The test harness
restarts the server (via start.sh) before each test, wiping all state.
"""

# Each map: id -> record dict
service_plans = {}
service_accounts = {}
collection_zones = {}
holidays = {}
cart_assignments = {}
pickup_schedules = {}
pickup_events = {}
extra_pickup_requests = {}
invoices = {}
payments = {}
missed_pickup_credits = {}
contamination_notices = {}

# Monotonic sequence to break created_at ties deterministically (insertion order).
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq
