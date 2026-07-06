"""Domain thresholds — numeric constants from the PRD's pricing and DSO rules."""

# Retainer tier table: base fee (cents), included transactions, per-txn overage
# rate in milli-dollars (thousandths of a dollar). PRD §3.8.
TIER_TABLE = {
    "ESSENTIALS": {"base_cents": 150000, "included_txns": 200, "overage_rate_milli": 750},
    "GROWTH": {"base_cents": 300000, "included_txns": 500, "overage_rate_milli": 600},
    "CFO": {"base_cents": 600000, "included_txns": 1200, "overage_rate_milli": 450},
}

# Included monthly transaction volume per tier (Client.included_txn_count). PRD §2.5.
INCLUDED_TXN_COUNT = {
    "ESSENTIALS": 200,
    "GROWTH": 500,
    "CFO": 1200,
}

# Catch-up surcharge fraction of the tier base fee. PRD §3.8.
SURCHARGE_PCT = 0.20

# DSO window in days. PRD §3.5.
DSO_PERIOD_DAYS = 30

# Logical clock startup default. PRD §2.10.
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

# Pagination defaults. PRD §2.3.
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "default_offset": 0}
