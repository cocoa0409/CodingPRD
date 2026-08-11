"""In-memory data store. Empty on every boot — nothing is ever seeded.

All entities live in module-level dicts keyed by id. A global monotonic
sequence number gives every row a stable insertion order used as the
tie-break for created_at-ordered listings.
"""

cases = {}
creditors = {}
claims = {}
objections = {}
assets = {}
sales = {}
actions = {}
deposits = {}
plans = {}
allocations = {}
dividends = {}
fees = {}
reports = {}  # keyed by report id; a case has at most one

_seq = [0]


def next_seq() -> int:
    _seq[0] += 1
    return _seq[0]
