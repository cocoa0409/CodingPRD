"""In-memory data store. All state starts empty on every boot.

No seeding, no preloading, no hardcoded entities. Every entity is created by
tests through the declared API surface. Keyed by id (UUID string).
"""

# One dict per entity type, keyed by id.
projects = {}
areas = {}
enumerators = {}
cases = {}
assignments = {}
attempts = {}
responses = {}
reinterviews = {}
pay_periods = {}
pay_lines = {}

# Monotonic sequence used to preserve stable creation order for list sorting
# (created_at timestamps can collide at millisecond resolution).
_seq_counter = [0]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def reset():
    """Not used at runtime; present only for completeness/testing."""
    for d in (projects, areas, enumerators, cases, assignments, attempts,
              responses, reinterviews, pay_periods, pay_lines):
        d.clear()
    _seq_counter[0] = 0
