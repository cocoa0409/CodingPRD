"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Settlement-fee rate bands selected by total enrolled balance (PRD §3.2).
FEE_TIER_LOW = 0.25      # total < 10000
FEE_TIER_MID = 0.22      # 10000 <= total < 30000
FEE_TIER_HIGH = 0.18     # total >= 30000

TIER_1_CEIL = 10000      # total < 10000 -> 0.25
TIER_2_CEIL = 30000      # 10000 <= total < 30000 -> 0.22 ; >= 30000 -> 0.18

# Litigation surcharge on offers for debts in LAWSUIT (PRD §3.5).
LITIGATION_SURCHARGE = 0.03
SURCHARGE_CAP = 0.25

# Offer due-date adjacency buffer (PRD §3.5).
MIN_OFFER_GAP_DAYS = 30

# 1099-C reportable floor (PRD §3.7).
REPORTABLE_FLOOR = 600

# Default forward-looking settlement assumption (PRD §3.1).
DEFAULT_TARGET_PCT = 0.50
DEFAULT_DEPOSIT_DAY = 1
DEFAULT_RESERVE_FLOOR = 0

# Delinquency ladder thresholds (PRD §2.9).
DELINQUENT_MIN_MISSED = 1
DEFAULTED_MIN_MISSED = 3

# Server startup logical-clock default (PRD §2.4).
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"
