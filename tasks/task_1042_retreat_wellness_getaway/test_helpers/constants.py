"""Domain thresholds — numeric constants from the PRD calculations and rules."""

# Charge calculation (PRD §3.2, §3.3)
SPECIAL_DIET_SURCHARGE_CENTS = 5000
DISCOUNT_TIER_2 = 0.08   # party_size 2 or 3
DISCOUNT_TIER_4 = 0.15   # party_size >= 4

# Tax and payment split (PRD §3.2, §2.6)
TAX_PCT = 0.085
DEPOSIT_PCT = 0.30

# Cancellation refund ladder (PRD §3.7), in whole days before start_date
FULL_REFUND_DAYS = 60
HALF_REFUND_DAYS = 30
QUARTER_REFUND_DAYS = 14

# Facilitator payout (PRD §3.5)
FACILITATOR_FLAT_CENTS = 40000   # provisional, per scheduled/completed slot
PER_HEAD_CENTS = 3000            # final, per confirmed attendee

# Activity slot room setup buffer (PRD §3.5)
SETUP_BUFFER_MINUTES = 30

# Test clock startup default (PRD §3.1)
DEFAULT_CLOCK = "2026-07-01T00:00:00Z"

# Convenience: the charge breakdown for a party_size-2 booking at base 150000
# in a STANDARD room with no add-ons and no special diet (PRD §3.2 worked math).
PARTY2_BASE150000 = {
    "subtotal_cents": 300000,
    "total_cents": 276000,
    "tax_cents": 25500,
    "grand_total_cents": 301500,
    "deposit_cents": 90450,
    "balance_due_cents": 211050,
}
