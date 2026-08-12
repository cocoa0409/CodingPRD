"""Domain thresholds and shared constants (PRD §2.4, §3.1, §3.5, §3.8)."""

# Logical clock starts here on a fresh deployment (PRD §2.4).
DEFAULT_SERVER_CLOCK = "2026-05-01T00:00:00Z"

# Standard pricing configuration used by most scenarios (PRD §3.1).
DEFAULT_PRICING = {
    "effective_from": "2026-01-01",
    "bottle_deposit_cents": 1500,
    "bottle_shortage_fee_cents": 2000,
    "standard_per_bottle_cents": 700,
    "silver_per_bottle_cents": 650,
    "gold_per_bottle_cents": 600,
    "silver_volume_threshold": 20,
    "gold_volume_threshold": 50,
    "late_fee_flat_cents": 1500,
}

# Rent proration constants (PRD §3.8): daily rate = monthly * 12 / 365, half-up.
DAYS_IN_YEAR = 365
MONTHS_IN_YEAR = 12

# Skip-credit rules (PRD §3.5): 24h notice cutoff, 50% late credit, 90-day expiry.
CUTOFF_HOURS = 24
LATE_SKIP_CREDIT_RATIO = 0.5
SKIP_CREDIT_EXPIRY_DAYS = 90
