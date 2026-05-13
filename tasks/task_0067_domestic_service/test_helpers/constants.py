"""Domain thresholds and numeric constants for the Domestic Service Dispatch API.

All values transcribed verbatim from PRD §2-§3 prose. The generic NON_EXISTENT_UUID
comes from the framework — do not redeclare it here.
"""

# ─── Performance tier thresholds (PRD §3.9) ───────────────────────────
MIN_SAMPLE_COUNT = 5
PLATINUM_FLOOR = 4.8
GOLD_FLOOR = 4.5
SILVER_FLOOR = 4.0

# ─── Tier bonus rates (PRD §3.10) ─────────────────────────────────────
BASE_COMMISSION_RATE = 0.70
PLATINUM_BONUS_RATE = 0.20
GOLD_BONUS_RATE = 0.10
SILVER_BONUS_RATE = 0.05
BRONZE_BONUS_RATE = 0.00

# ─── Settlement (PRD §3.10) ───────────────────────────────────────────
TAX_RATE = 0.10
WITHHELD_HOURS = 72

# ─── Dispatch / workload (PRD §3.5) ───────────────────────────────────
MAX_WORKLOAD = 5
DISPATCH_DEADLINE_MINUTES = 15

# ─── Order temporal windows (PRD §3.4, §3.5, §3.6, §3.8) ──────────────
LEAD_TIME_HOURS = 1
MODIFY_WINDOW_HOURS = 12
CANCEL_WINDOW_HOURS = 2
COMPLAINT_WINDOW_HOURS = 72
CHECKIN_EARLY_WINDOW_MINUTES = 15

# ─── Checkin geographic gate (PRD §2.9, §3.6) ─────────────────────────
CHECKIN_RADIUS_KM = 0.2
DEFAULT_SERVICE_RADIUS_KM = 10

# ─── Personnel age constraint (PRD §3.1) ──────────────────────────────
PERSONNEL_MIN_AGE = 18
PERSONNEL_MAX_AGE = 70

# ─── SkillCertification (PRD §3.2) ────────────────────────────────────
MIN_TRAINING_HOURS = 8

# ─── Service item defaults (PRD §3.3) ─────────────────────────────────
DEFAULT_MIN_DURATION_HOURS = 1

# ─── Rating weights (PRD §3.9) ────────────────────────────────────────
WEIGHT_QUALITY = 0.5
WEIGHT_PUNCTUALITY = 0.3
WEIGHT_ATTITUDE = 0.2
RATING_MIN = 1
RATING_MAX = 5
INVESTIGATION_THRESHOLD = 3.0

# ─── Claim file gate (PRD §3.7) ───────────────────────────────────────
MIN_EVIDENCE_FOR_FILE = 2

# ─── Recurring order cadence (PRD §3.4) ───────────────────────────────
ALLOWED_CADENCE_DAYS = (1, 7, 14, 30)

# ─── Pagination (PRD §2.3) ────────────────────────────────────────────
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# Tier priority for dispatch ranking (PRD §3.5)
TIER_PRIORITY = {
    "PLATINUM": 4,
    "GOLD": 3,
    "SILVER": 2,
    "BRONZE": 1,
}


TEST_DEFAULTS = {
    "BASE_PRICE_CENTS": 10000,          # 100.00 per service hour
    "DURATION_HOURS": 2.0,
    "DEFAULT_GROSS_CENTS": 20000,       # base * duration
    # Default geographic placement — Beijing-ish, well within 10km radius
    "LAT": 39.9042,
    "LNG": 116.4074,
    "AREA": "CN-11-001",
    "FAR_LAT": 40.5,                    # ~66 km away — outside 10km radius
    "FAR_LNG": 117.0,
}
