"""Domain thresholds — numeric constants from the PRD calculations and fiscal rules."""

# Brokerage commission (marginal Lehman ladder) — PRD Section 3.8.
TIER_WIDTH_CENTS = 100_000_000          # one million dollars per tier
MIN_COMMISSION_CENTS = 1_500_000        # commission floor (fifteen thousand dollars)

# Qualification capacity — PRD Section 3.4.
DOWN_PAYMENT_PCT = 0.10                  # required down payment = 10% of asking
NET_WORTH_MULTIPLE = 2.0                 # net-worth ceiling multiplier
SBA_MAX_CENTS = 500_000_000             # program cap (five million dollars)

# Settlement waterfall — PRD Section 3.8.
ESCROW_FEE_PCT = 0.01                    # escrow fee = 1% of closing price

# Earnout performance — PRD Section 3.9.
EARNOUT_CAP_RATIO = 1.5                  # performance ratio ceiling

# Management-meeting scheduling buffer — PRD Section 3.3.
MEETING_BUFFER_MINUTES = 30

# Convenience test defaults (all integer cents unless noted).
TEST_DEFAULTS = {
    "ASKING_PRICE": 120_000_000,
    "ANNUAL_SDE": 40_000_000,
    "INDUSTRY_MULTIPLE": 3.0,
    "FFE_VALUE": 20_000_000,
    "INVENTORY_VALUE": 10_000_000,
    "ANNUAL_REVENUE": 150_000_000,
    "BUYER_PROOF_OF_FUNDS": 30_000_000,
    "BUYER_NET_WORTH": 150_000_000,
    "OFFER_PRICE": 115_000_000,
    "EARNEST_DEPOSIT": 5_000_000,
    "CLOSING_PRICE": 110_000_000,
    "REQUIRED_DEPOSIT": 5_000_000,
    "LOAN_REQUESTED": 99_000_000,
}
