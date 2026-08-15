"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No entity seeding: every collection starts empty; tests build all state via the API.
"""

COLLECTIONS = [
    "funds",
    "share_classes",
    "nav_periods",
    "series",
    "investors",
    "kyc_cases",
    "accreditations",
    "subscriptions",
    "side_letters",
    "mfn_clauses",
    "capital_accounts",
    "series_lots",
    "redemptions",
    "statements",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic insertion sequence used as a stable tie-break for created_at sorting.
_seq_counter = [0]


def next_seq() -> int:
    _seq_counter[0] += 1
    return _seq_counter[0]
