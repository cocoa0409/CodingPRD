"""Domain thresholds — numeric constants from the PRD's calculations (§2.9, §3.2, §3.6)."""

# permit_class thresholds (PRD §3.2)
PERMIT_CLASS = {
    "SMALL_MAX": 1000,   # attendance <= 1000 -> SMALL
    "MEDIUM_MAX": 5000,  # 1001..5000 -> MEDIUM; 5001+ -> LARGE
}

# application fee (PRD §3.2)
BASE_FEE = {"SMALL": 150.00, "MEDIUM": 400.00, "LARGE": 900.00}
TIER2_RATE = 0.20   # per head 1001..5000
TIER3_RATE = 0.35   # per head above 5000
SEGMENT_FEE = 75.00  # per route segment

# cleanup deposit (PRD §3.2)
CLEANUP_FLOOR = {"SMALL": 200.00, "MEDIUM": 500.00, "LARGE": 1500.00}
PER_HEAD_RATE = 0.10

# insurance coverage minimum (PRD §3.2)
COI_BASE = 1_000_000
COI_PER_HEAD = 100
COI_CAP = 5_000_000

# cost recovery (PRD §3.6, §3.8)
OVERHEAD_RATE = 0.15

# venue / closure defaults (PRD §2.7, §2.8)
DEFAULT_SETUP_BUFFER_MINUTES = 60
DEFAULT_MIN_GAP_MINUTES = 30

# pagination defaults (PRD §2.3)
DEFAULT_LIMIT = 10
