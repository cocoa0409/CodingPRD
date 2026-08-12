"""Domain thresholds and defaults — numeric constants from the PRD (section 3)."""

# Guide-to-student ratio classification boundaries (PRD 3.4).
RATIO_COMPLIANT_MIN = 0.1            # ratio >= 1/10 -> COMPLIANT
RATIO_VIOLATION_MIN = 1.0 / 15.0     # ratio >= 1/15 -> AT_RISK; below -> VIOLATION
WEEKLY_HOURS_CAP = 30                # weekly hours capped at 30 for ratio purposes

# Licensing exemption eligibility (PRD 3.3).
EXEMPTION_MAX_SEAT_CAPACITY = 10
EXEMPTION_ZONING_CLASSES = ["RESIDENTIAL_SINGLE", "RELIGIOUS", "AGRICULTURAL"]

# Tiered administration fee (PRD 3.7).
ADMIN_FEE_TIER1_MAX_ENROLLED = 8
ADMIN_FEE_TIER2_MAX_ENROLLED = 16
ADMIN_FEE_TIER3_MAX_ENROLLED = 24
ADMIN_FEE_TIER1_PCT = 0.04
ADMIN_FEE_TIER2_PCT = 0.03
ADMIN_FEE_TIER3_PCT = 0.02
ADMIN_FEE_TIER4_PCT = 0.015

# Curriculum plan weekly minutes floor (PRD 3.2).
CURRICULUM_MIN_WEEKLY_MINUTES = 1200

# Safety policy content requirements (PRD 3.2).
EMERGENCY_PLAN_MIN_CHARS = 200
DRILL_CADENCE_MIN_DAYS = 7
DRILL_CADENCE_MAX_DAYS = 90

# Withdrawal refund sliding-scale tiers, in enrolled days (PRD 3.9).
REFUND_TIER1_MAX_DAYS = 14
REFUND_TIER2_MAX_DAYS = 45
REFUND_TIER3_MAX_DAYS = 90

# Voucher funding-status threshold (PRD 3.7).
VOUCHER_FUNDED_THRESHOLD_PCT = 0.50

# Progress conference reschedule cap (PRD 3.8).
CONFERENCE_CYCLE_LIMIT = 3

# Seat capacity bounds (PRD 3.1).
SEAT_CAPACITY_MIN = 5
SEAT_CAPACITY_MAX = 30

TEST_DEFAULTS = {
    "JURISDICTION_CODE": "AZ-MARICOPA",
    "ACADEMIC_YEAR": "2026-2027",
    "TERM_START_DATE": "2026-08-01",
    "TERM_END_DATE": "2027-05-31",
    "TUITION_FULL_YEAR_CENTS": 1200000,
    "SEAT_CAPACITY": 12,
    "MIN_GUIDES_REQUIRED": 1,
    "WEEKLY_HOURS": 30,
    "PLAN_MINUTES": 1500,
    "DRILL_CADENCE_DAYS": 30,
    "BILLING_STATE": "AZ",
    "VOUCHER_PROGRAM_CODE": "AZ-ESA",
}

# Standard academic year used by composite fixtures:
# 2026-08-01 .. 2027-05-31 inclusive is 303 days apart + 1 = 304 total days.
TERM_TOTAL_DAYS = 304
