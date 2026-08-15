"""In-memory data store. Fresh on every process boot (per-test-server isolation).

Nothing is seeded here: every entity is constructed through the declared API
surface at request time. The store is plain dicts keyed by resource id.
"""
import itertools

COLLECTIONS = [
    "drugs",
    "asp_schedules",
    "clinical_policies",
    "provider_accounts",
    "prior_authorizations",
    "claims",
    "claim_adjustments",
    "redirections",
    "biosimilar_policies",
    "pipeline_drugs",
    "spend_forecasts",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic insertion sequence: authoritative tie-break for "created_at" ordering
# (the logical clock can produce identical timestamps for consecutive creates).
_seq_counter = itertools.count(1)


def next_seq() -> int:
    return next(_seq_counter)
