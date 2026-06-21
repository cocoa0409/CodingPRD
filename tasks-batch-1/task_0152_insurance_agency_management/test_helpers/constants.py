"""Domain thresholds — numeric constants from the PRD's calculations (§3.5, §3.6, §3.8)."""

# Commission volume-tier ceilings & multipliers (PRD §3.5).
# < 100_000 cents -> 1.00; [100_000, 500_000) -> 1.05; >= 500_000 -> 1.10.
TIER1_CEIL_CENTS = 100_000
TIER2_CEIL_CENTS = 500_000
TIER1_MULT = 1.00
TIER2_MULT = 1.05
TIER3_MULT = 1.10

# Short-rate cancellation penalty (PRD §3.6): refund 90% of pro-rata unearned.
SHORT_RATE_PENALTY = 0.10

# Renewal window opens 60 days before expiration (PRD §3.8).
RENEWAL_WINDOW_DAYS = 60

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
MIN_LIMIT = 1
