"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No seeding: every entity is created via the declared API surface.
"""
import itertools

COLLECTIONS = [
    "carriers",
    "drivers",
    "violation_categories",
    "roadside_inspections",
    "inspection_violations",
    "dataqs_challenges",
    "coaching_assignments",
    "drug_alcohol_tests",
    "accident_records",
    "compliance_audit_cases",
    "rating_upgrade_requests",
    "insurance_premium_models",
    "document_records",
    "random_testing_periods",
    "measurement_snapshots",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic insertion sequence — stable list ordering (created_at ascending).
_seq_counter = itertools.count(1)


def next_seq() -> int:
    return next(_seq_counter)
