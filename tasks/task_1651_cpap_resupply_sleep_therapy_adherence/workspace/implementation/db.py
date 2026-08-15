"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No seeding: every collection starts empty; tests construct all state via the API.
"""
import itertools

COLLECTIONS = [
    "payer_policies",
    "patients",
    "device_enrollments",
    "component_supply_plans",
    "resupply_orders",
    "adherence_reports",
    "mask_exchanges",
    "rental_contracts",
    "retrieval_cases",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic insertion sequence — deterministic "most recently created" ordering
# even when several records share the same logical-clock created_at.
_seq = itertools.count(1)


def next_seq() -> int:
    return next(_seq)
