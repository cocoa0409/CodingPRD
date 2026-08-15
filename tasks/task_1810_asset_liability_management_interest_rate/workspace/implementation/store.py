"""In-memory data store.

The store starts EMPTY on every boot. No entity is ever seeded, preloaded,
or hardcoded at startup; every record is created through the declared API
surface. ``--isolation per-test-server`` re-launches the server before every
test, so each test sees a pristine store.
"""

books = {}
positions = {}
assumption_sets = {}
scenarios = {}
runs = {}
policy_limits = {}
breaches = {}
hedges = {}
eff_tests = {}
backtests = {}
reports = {}

# Monotonic insertion sequence used as a stable tiebreak when several records
# share the same logical-clock created_at instant.
_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]
