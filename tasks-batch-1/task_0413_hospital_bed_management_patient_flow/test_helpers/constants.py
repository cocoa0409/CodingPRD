"""Domain thresholds — numeric constants from the PRD's calculations."""

# Unit posture thresholds (PRD §2.7). Inclusive (>=).
SURGE_HIGH_PCT = 85.0
SURGE_CRITICAL_PCT = 95.0

# ED boarding SLA (PRD §3.3). Inclusive (>=).
ED_BOARDING_SLA_HOURS = 4.0

# Long-stay multiplier (PRD §3.7): threshold = gmlos_days * 24 * LONG_STAY_MULT.
LONG_STAY_MULT = 1.5

# Placement match-score weights (PRD §3.4).
ISO_WASTE_PENALTY = -10
TELE_WASTE_PENALTY = -5
PREFERRED_UNIT_BONUS = 50
PLACEMENT_POSTURE_BONUS = {"GREEN": 20, "YELLOW": 10, "RED": 0, "CLOSED": 0}

# EVS priority-score weights (PRD §3.9).
EVS_TYPE_BASE = {"STAT": 100, "ISOLATION": 70, "ROUTINE": 40}
EVS_POSTURE_BONUS = {"RED": 30, "YELLOW": 15, "GREEN": 0, "CLOSED": 0}
EVS_AGING_WINDOW_MIN = 30
EVS_AGING_STEP = 5

# BedRequest expiry (PRD §3.4): QUEUED requests aged >= 2 ops runs expire.
REQUEST_EXPIRY_RUNS = 2

# Default gmlos_days when omitted on POST /units (PRD §3.1).
DEFAULT_GMLOS_DAYS = 3

# Pagination bounds (PRD §2.3).
PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100

# A path-shaped UUID that resolves to nothing (for 404 path tests).
NON_EXISTENT_PATH_UUID = "00000000-0000-4000-8000-000000000000"
