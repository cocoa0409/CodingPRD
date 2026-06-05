"""Domain thresholds — numeric constants from PRD calculations and rules."""

# ─── Tiered refund (PRD §3.7) ─────────────────────────────────────────────────
FULL_REFUND_DAYS = 60       # days_before >= 60 -> FULL
PARTIAL_75_DAYS = 14        # days_before >= 14 -> PARTIAL_75
PARTIAL_50_DAYS = 1         # days_before >= 1  -> PARTIAL_50
PCT_75 = 0.75
PCT_50 = 0.50

# ─── Standby promotion score (PRD §3.6) ───────────────────────────────────────
TIER_WEIGHT_FEE_WAIVER = 300
TIER_WEIGHT_SCHOOL_DAY = 200
TIER_WEIGHT_GENERAL = 100
RECENCY_CAP_HOURS = 48

# ─── Allotted minutes / base minutes (PRD §3.5) ───────────────────────────────
BASE_MINUTES_SAT = 134
BASE_MINUTES_ACT = 175
BASE_MINUTES_AP = 180
MULT_EXTENDED_TIME_50 = 1.5
MULT_EXTENDED_TIME_100 = 2.0
MULT_SEPARATE_ROOM = 1.0
MULT_BREAKS_ONLY = 1.0

# ─── CLEP credit recognition (PRD §3.9) ───────────────────────────────────────
CLEP_PASS_THRESHOLD = 50
CLEP_HOURS_TIER_1 = 3       # [50, 60)
CLEP_HOURS_TIER_2 = 6       # [60, 70)
CLEP_HOURS_TIER_3 = 9       # >= 70

# ─── Rest separation for accommodated sittings (PRD §3.5) ─────────────────────
REST_BUFFER_HOURS = 3

# ─── AP fee settlement (PRD §3.3) ─────────────────────────────────────────────
DEFAULT_FEE_REDUCTION_PCT = 0.0

# ─── Pagination defaults (PRD §2.3) ───────────────────────────────────────────
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
