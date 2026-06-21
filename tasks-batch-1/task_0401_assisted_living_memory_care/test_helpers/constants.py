"""Domain thresholds — numeric constants from the PRD calculations (Section 3)."""

# --- care_points_total (Section 3.2) ---
ADL_POINT_WEIGHT = 3
COGNITION_WEIGHT = 2
BEHAVIOR_WEIGHT = 5
BEHAVIOR_FLAG_CAP = 4

# --- care_level_assignment (Section 3.2) ---
MEMORY_CARE_COGNITION_THRESHOLD = 7
LEVEL_2_MIN_POINTS = 30
LEVEL_3_MIN_POINTS = 55

# --- facility_occupancy (Section 3.1) ---
BPS_SCALE = 10000

# --- poc_due_date (Section 3.10) ---
STANDARD_POC_WINDOW_DAYS = 10
IJ_POC_WINDOW_DAYS = 2

# --- Canonical billing literals (pre-computed in the design indices) ---
# Facility care_point_rate_cents 1500; unit base rent 401500; resident LEVEL_2 cp 30.
# care_points_month = 30 * 1500 = 45000.
CANONICAL_CARE_POINT_RATE_CENTS = 1500
CANONICAL_BASE_RENT_CENTS = 401500
CANONICAL_CARE_POINTS = 30
CANONICAL_CARE_MONTH_CENTS = 45000

# Full-month statement total (no proration): 401500 + 45000 + 0.
CANONICAL_FULL_MONTH_TOTAL_CENTS = 446500

# First/prorated statement, Jan 2026 (31 days), move-in day 10 (22 billable days),
# community fee 250000: per-line round-then-sum.
CANONICAL_PRORATED_RENT_CENTS = 284935
CANONICAL_PRORATED_CARE_CENTS = 31935
CANONICAL_COMMUNITY_FEE_CENTS = 250000
CANONICAL_PRORATED_TOTAL_WITH_FEE_CENTS = 566870       # 284935 + 31935 + 250000
CANONICAL_PRORATED_TOTAL_NO_FEE_CENTS = 316870         # 284935 + 31935
