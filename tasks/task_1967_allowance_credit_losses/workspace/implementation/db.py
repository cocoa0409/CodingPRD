"""In-memory data store for the CECL Allowance API.

Storage is pure in-memory dicts keyed by id. No persistence of any kind;
a fresh process boot starts with a completely empty store.
"""

# Entity collections, keyed by resource id (UUID string)
loss_models = {}
segments = {}
loans = {}
scenarios = {}
factors = {}
runs = {}
evaluations = {}
adjustments = {}
reports = {}
backtest_results = {}

# Monotonic creation counter used as a tiebreaker for created_at ordering.
# Guarantees a strictly ascending creation order even when two resources are
# created within the same millisecond.
creation_counter = 0


def next_creation_seq():
    global creation_counter
    creation_counter += 1
    return creation_counter
