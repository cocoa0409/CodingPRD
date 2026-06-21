"""Domain thresholds and numeric constants drawn from the PRD."""

# ---------- Quarter-of-coverage thresholds (PRD §3.2) ----------
RECENT_QC_THRESHOLD = 20       # quarters required in 10-year lookback
MAX_REQUIRED_TOTAL_QC = 40     # cap on age-adjusted total
LOOKBACK_YEARS = 10            # 10-year recent-work window
MIN_REQUIRED_TOTAL_QC_UNDER_24 = 6  # under-24 fixed requirement

# ---------- PIA bend-point constants (PRD §3.6) ----------
BEND1_CENTS = 117_400          # first bend point: $1,174.00
BEND2_CENTS = 707_900          # second bend point: $7,079.00
TIER1_RATE = 0.90
TIER2_RATE = 0.32
TIER3_RATE = 0.15
AIME_DIVISOR_CAP = 35          # top-N years cap

# ---------- Back-pay constants (PRD §3.6) ----------
WAITING_PERIOD_MONTHS = 5
MAX_RETROACTIVE_MONTHS_BEFORE_PFD = 12

# ---------- SSI supplement constants (PRD §3.7) ----------
FBR_CENTS = 94_300             # federal benefit rate 2024 single individual
RESOURCE_LIMIT_CENTS = 200_000 # countable resources strict-> ineligible
GENERAL_EXCLUSION_CENTS = 2_000

STATE_SUPPLEMENT_TABLE = {
    "CA": 2_050,
    "NY": 8_700,
    # all other states default to 0
}

# ---------- Child auxiliary (PRD §3.8) ----------
CHILD_RATE = 0.50
FAMILY_MAX_MULTIPLIER = 1.75

# ---------- CDR scheduling (PRD §3.9) ----------
MIE_MONTHS = 18
MIP_MONTHS = 36
MINE_MONTHS = 84

# ---------- ALJ hearing lead time (PRD §3.5) ----------
HEARING_LEAD_TIME_DAYS = 75

# ---------- Reconsideration filing window (PRD §3.5) ----------
RECONSIDERATION_WINDOW_DAYS = 60

# ---------- Child age cap (PRD §3.8) ----------
CHILD_MAX_AGE_YEARS = 18
