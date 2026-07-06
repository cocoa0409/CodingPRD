"""Domain thresholds — numeric constants stated in the PRD pricing/refund rules (§3.5, §3.6)."""

# Head-table supplement added to a HEAD_TABLE seat's base price (PRD §3.5).
HEAD_TABLE_SUPPLEMENT_CENTS = 2000

# Group-discount pricing parameters (PRD §3.5).
GROUP_DISCOUNT_MIN_PARTY = 6      # discount applies when party_size is at least 6
GROUP_LARGE_PARTY = 10            # rate 0.15 when party_size is at least 10
GROUP_RATE_SMALL = 0.10
GROUP_RATE_LARGE = 0.15
MAX_DISCOUNT_CENTS = 15000        # discount never exceeds this cap

# Cancellation refund tiers, in whole days before the event (PRD §3.6).
FULL_REFUND_DAYS = 14            # >= 14 days -> 1.00
HALF_REFUND_DAYS = 7            # >= 7 and < 14 -> 0.50
QUARTER_REFUND_DAYS = 2         # >= 2 and < 7 -> 0.25
# < 2 days -> 0.00

# Logical-clock startup default (PRD §2.8).
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"
