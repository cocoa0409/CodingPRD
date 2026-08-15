"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No entity is ever seeded: the store starts empty and every row is created
through a declared API endpoint.
"""
import itertools

COLLECTIONS = [
    "drawings",
    "components",
    "consigned_lots",
    "operators",
    "operator_certifications",
    "applicators",
    "applicator_setups",
    "machine_programs",
    "build_orders",
    "kits",
    "harness_units",
    "crimp_pull_tests",
    "electrical_test_records",
    "ecns",
]

db = {name: {} for name in COLLECTIONS}

_seq_counter = itertools.count(1)


def next_seq() -> int:
    """Monotonic insertion sequence; stable tie-break for equal created_at."""
    return next(_seq_counter)
