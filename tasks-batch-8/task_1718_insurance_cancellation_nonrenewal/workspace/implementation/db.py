"""In-memory data store.

Pure Python dicts keyed by id. Nothing is persisted to disk, so every
`start.sh` re-invocation boots with a completely empty store. No entity is
ever seeded here — tests construct all state through the declared API.
"""

# Entity tables: id -> dict
state_profiles = {}
policyholders = {}
policies = {}
insured_interests = {}
cancellation_cases = {}
nonrenewal_cases = {}
notices = {}
ledger_entries = {}
reinstatement_requests = {}
appeals = {}
regulatory_reports = {}

# Monotonic insertion counter used as a stable chronological tiebreak for
# resources created within the same timestamp tick.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq
