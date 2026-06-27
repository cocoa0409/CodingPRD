"""Domain thresholds — numeric constants from the PRD calculations (section 3).

All money is integer cents (PRD section 2.6). round_half_up applies wherever a
percentage produces a fractional cent.
"""

# ─── Fee assessment (PRD section 3.2) ────────────────────────────────────
ZONING_SURCHARGE_PCT = 0.10
MANUFACTURER_SURCHARGE_PCT = 0.25
RENEWAL_LATE_FEE_PCT = 0.05  # 5% of base when clock has reached term_end_at

# ─── Fine assessment (PRD section 3.9) ───────────────────────────────────
SEVERITY_BASE_CENTS = {
    "MINOR": 25000,
    "SERIOUS": 75000,
    "EGREGIOUS": 200000,
}
RECIDIVISM_LOW = 1.0    # prior demerit_points < 4
RECIDIVISM_MID = 1.5    # prior demerit_points 4..8
RECIDIVISM_HIGH = 2.0   # prior demerit_points > 8
FINE_CAP_CENTS = 500000
SUSPENSION_FINE_FACTOR = 0.5  # SUSPENSION halves the raw fine

# Demerit points added on a sustained violation, by severity (PRD section 3.9).
DEMERIT_FOR = {
    "MINOR": 2,
    "SERIOUS": 4,
    "EGREGIOUS": 6,
}
DEMERIT_SUSPENSION_THRESHOLD = 10  # demerit_points >= 10 suspends / blocks renew

# ─── Excise assessment (PRD section 3.11) ────────────────────────────────
EXCISE_TIER1_CAP_CENTS = 1_000_000
EXCISE_TIER2_CAP_CENTS = 4_000_000  # band width for the 1M..5M portion
EXCISE_TIER1_RATE = 0.02
EXCISE_TIER2_RATE = 0.04
EXCISE_TIER3_RATE = 0.06
# Rebate base tiers, keyed on the excise total.
EXCISE_REBATE_LOW_CAP = 50_000      # excise <= 50000 -> rebate 0
EXCISE_REBATE_MID_CAP = 200_000     # 50001..200000 -> 5% rebate base
EXCISE_REBATE_MID_RATE = 0.05
EXCISE_REBATE_HIGH_RATE = 0.10      # excise > 200000 -> 10% rebate base
EXCISE_TIER_MULTIPLIER = {
    "SUPPLIER": 2.0,
    "WHOLESALER": 1.0,
    "RETAILER": 0.0,
}

# ─── Zoning buffer (PRD section 3.3) ─────────────────────────────────────
BUFFER_METRES_REQUIRED = 100  # ON_PREMISE / OFF_PREMISE; MANUFACTURER requires 0

# ─── Temporal constants (PRD sections 3.2, 3.5, 3.7, 3.8) ─────────────────
PROTEST_PERIOD_DAYS = 30
RENEWAL_WINDOW_LEAD_DAYS = 60
SERVER_PERMIT_TERM_MONTHS = 36

# ─── Pagination (PRD section 2.3) ────────────────────────────────────────
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# ─── Server clock default (PRD section 2.4) ──────────────────────────────
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"
