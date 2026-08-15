"""In-memory data store.

The store starts completely empty on every boot (per-test-server isolation
re-launches the process before every test). No seeding of any kind.
"""

import itertools

# Entity tables: id -> dict
terms = {}
breaks = {}
students = {}
enrollments = {}
awards = {}
disbursements = {}
withdrawal_cases = {}
obligations = {}
offers = {}
account_entries = {}

# Monotonic creation sequence used as a tiebreaker where created_at
# timestamps could collide (same logical instant).
_creation_seq = itertools.count(1)


def next_seq() -> int:
    return next(_creation_seq)


def reset_all():
    """Clear every table (used only by tests of the module itself)."""
    for table in (terms, breaks, students, enrollments, awards,
                  disbursements, withdrawal_cases, obligations, offers,
                  account_entries):
        table.clear()
