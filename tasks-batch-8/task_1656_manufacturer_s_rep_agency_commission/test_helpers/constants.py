"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock default reading before any advance (PRD §2.5).
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Global rule constants (PRD §2.6, §3.3, §3.6, §3.7, §3.8).
THRESHOLDS = {
    "PROTECTION_DAYS": 180,          # registration protection window length
    "RENEWAL_DAYS": 90,              # protection extension per renewal
    "RENEWAL_WINDOW_DAYS": 30,       # renewal allowed within 30d before end
    "RENEWAL_LIMIT": 1,              # one renewal per registration
    "CHECKOUT_DAYS": 30,             # sample checkout length
    "CHECKOUT_BUFFER_DAYS": 1,       # inspection buffer after a checkout
    "RMA_RECEIPT_WINDOW_DAYS": 45,   # approved RMA lapses 45d after approval
    "REP_HOLD_FLOOR_CENTS": -50_000,  # hold engages below this balance
    "LINE_TOLERANCE_CENTS": 25,      # statement line match tolerance (inclusive)
    "DRAW_RECOVERY_BP": 5000,        # half of gross skimmed against the draw
    "DEPRECIATION_STEP_BP": 1500,    # 15% of list per started 30-day month
    "RESIDUAL_FLOOR_BP": 2000,       # never charges below 20% of list
    "DAMAGED_RETURN_BP": 5000,       # damaged return charges 50% of depreciated
}

TEST_DEFAULTS = {
    "QUOTA_CENTS": 10_000_000,
    "NOTICE_PERIOD_DAYS": 90,
    "TAIL_PERIOD_DAYS": 180,
    "SPECIFY_SHARE_BP": 6000,
    "REGISTERED_PROTECTION_SHARE_BP": 10000,
    "REGISTRATION_BONUS_BP": 200,
    "EFFECTIVE_START": "2026-01-01T00:00:00Z",
}

# Canonical rate schedule used by the shared base fixture: CONNECTORS 1000bp,
# CABLES 800bp; tiers 0% -> x1.00, 80% -> x1.10, 100% -> x1.25.
BASE_FAMILY_RATES = [
    {"family_code": "CONNECTORS", "base_rate_bp": 1000},
    {"family_code": "CABLES", "base_rate_bp": 800},
]
BASE_ATTAINMENT_TIERS = [
    {"min_attainment_bp": 0, "multiplier_bp": 10000},
    {"min_attainment_bp": 8000, "multiplier_bp": 11000},
    {"min_attainment_bp": 10000, "multiplier_bp": 12500},
]
