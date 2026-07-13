"""Domain thresholds and constants drawn from the PRD's calculations and rules."""

# --- Fiscal / lifecycle thresholds (PRD §3.5, §3.7, §3.8) ---
PAYOUT_THRESHOLD_CENTS = 10000        # payout gross must be >= this (§3.7)
CLEARING_DAYS = 30                    # download.available_at = created_at + 30 days (§3.4)
SUSPEND_STRIKE_THRESHOLD = 3          # strike_count reaching 3 suspends (§3.8)
TAKEDOWN_HOLD_DAYS = 90               # hold_end = hold_start + 90 days (§3.8)
TAKEDOWN_BUFFER_DAYS = 14            # refile buffer after a prior UPHELD hold (§3.8)
SIMILAR_MAX_DISTANCE = 5             # Hamming distance <= 5 is SIMILAR (§3.3)

# --- Career royalty level thresholds on lifetime_earnings_cents (PRD §3.5) ---
LEVEL_SILVER_MIN = 25000
LEVEL_GOLD_MIN = 100000
LEVEL_PLATINUM_MIN = 500000

# --- Royalty-rate calculation constants (PRD §3.4) ---
EDITORIAL_BONUS_PCT = 0.05
RATE_CAP_PCT = 0.45
ROYALTY_MATRIX = {
    "NON_EXCLUSIVE": {"BRONZE": 0.15, "SILVER": 0.20, "GOLD": 0.25, "PLATINUM": 0.30},
    "EXCLUSIVE": {"BRONZE": 0.25, "SILVER": 0.30, "GOLD": 0.35, "PLATINUM": 0.40},
}

# --- Withholding constant (PRD §3.7) ---
DEFAULT_FOREIGN_WITHHOLDING_PCT = 0.30

# --- Logical clock (PRD §2.5) ---
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"
