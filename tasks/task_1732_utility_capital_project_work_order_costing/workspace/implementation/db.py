"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts EMPTY on every boot — no seeding of any kind. Every entity a
test needs is constructed through the declared API surface.
"""

COLLECTIONS = [
    "capital_programs",
    "unit_catalog",
    "overhead_schedules",
    "accounting_periods",
    "work_orders",
    "estimates",
    "cost_charges",
    "ciac_agreements",
    "fixed_asset_units",
    "regulatory_assets",
    "afudc_entries",
    "depreciation_entries",
    "amortization_entries",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic insertion sequence, used as a deterministic tiebreak after
# created_at (which has only millisecond resolution) in list ordering.
_seq = [0]


def next_seq() -> int:
    _seq[0] += 1
    return _seq[0]
