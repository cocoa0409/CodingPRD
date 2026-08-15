"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts completely empty — tests build all preconditions through the
declared API surface. A monotone `_seq` insertion counter provides the
deterministic tie-break for rows sharing one logical-clock created_at (the
UUID id is never used as a sort key).
"""

COLLECTIONS = [
    "rate_cases",
    "intervenors",
    "test_year_entries",
    "adjustments",
    "rate_base_items",
    "customer_classes",
    "data_requests",
    "settlement_proposals",
    "settlement_signatories",
    "regulatory_assets",
    "amortization_entries",
    "tariff_rates",
    "compliance_filings",
]

db = {name: {} for name in COLLECTIONS}

_seq_counter = [0]


def next_seq() -> int:
    _seq_counter[0] += 1
    return _seq_counter[0]
