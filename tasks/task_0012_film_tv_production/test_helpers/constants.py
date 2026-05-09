"""Domain thresholds and numeric constants from the PRD.

All monetary values are in integer cents (PRD §2.8). Timestamps are ISO 8601 UTC
with three fractional digits (PRD §2.4).
"""

# --- Budget category alert thresholds (PRD §2.7) ---
# utilization = (committed + actual) / planned
# > 1.00 → OVER ; >= 0.90 → WARN ; otherwise OK ; 1.00 itself is WARN, not OVER.
ALERT_WARN_THRESHOLD = 0.90  # inclusive lower bound for WARN
ALERT_OVER_THRESHOLD = 1.00  # strictly greater than this maps to OVER


# --- Cast commit calculation (PRD §3.2) ---
MINUTES_PER_SHOOT_DAY = 480
CAST_COMMIT_CAP_PRINCIPAL = 60
CAST_COMMIT_CAP_SUPPORTING = 30
CAST_COMMIT_CAP_FEATURED_BACKGROUND = 10

CAP_BY_TIER = {
    "PRINCIPAL": CAST_COMMIT_CAP_PRINCIPAL,
    "SUPPORTING": CAST_COMMIT_CAP_SUPPORTING,
    "FEATURED_BACKGROUND": CAST_COMMIT_CAP_FEATURED_BACKGROUND,
}


# --- Crew payroll overtime tiers (PRD §3.8) ---
OT_TIER_BREAK_DAYS = 5      # first 5 OT days at 1.50x
OT_FIRST_MULT = 1.50
OT_SECOND_MULT = 1.75


# --- Travel-buffer rules (PRD §3.4) ---
SAME_ZONE_BUFFER_MINUTES = 60
CROSS_ZONE_BUFFER_MINUTES = 240


# --- Scene duration bounds (PRD §3.4) ---
SCENE_MIN_DURATION_MINUTES = 1
SCENE_MAX_DURATION_MINUTES = 720


# --- Pagination (PRD §2.3) ---
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


# --- Title length bounds (PRD §3.1) ---
TITLE_MIN_LEN = 1
TITLE_MAX_LEN = 200


# --- Test fixture defaults (sized for boundary tests) ---
DEFAULT_TOTAL_BUDGET_CENTS = 200_000_000     # 2,000,000.00
DEFAULT_RESERVE_FUND_CENTS = 20_000_000      # 200,000.00
DEFAULT_CAST_PLANNED_CENTS = 50_000_000      # 500,000.00
DEFAULT_CREW_PLANNED_CENTS = 50_000_000
DEFAULT_EQUIPMENT_PLANNED_CENTS = 30_000_000
DEFAULT_LOCATION_PLANNED_CENTS = 20_000_000
DEFAULT_POST_PLANNED_CENTS = 20_000_000
DEFAULT_MISC_PLANNED_CENTS = 10_000_000
