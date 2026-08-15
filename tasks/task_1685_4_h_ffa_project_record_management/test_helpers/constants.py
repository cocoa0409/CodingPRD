"""Domain thresholds and fixed program-year constants from the PRD."""

THRESHOLDS = {
    # Record book scoring (PRD §3.5)
    "LEADERSHIP_BONUS": 5,
    "LATE_PENALTY_PER_DAY": 3,
    "LATE_PENALTY_CAP": 15,
    # Award rubric tiers (PRD §3.9)
    "TIER_GOLD": 85,
    "TIER_SILVER": 70,
    "TIER_BRONZE": 55,
    "LEADERSHIP_CAP": 20,
    # Scholarship points (PRD §3.9)
    "SCHOLARSHIP_BASE_POINTS": 7,
    "SCHOLARSHIP_GRANT_MIN_POINTS": 30,
    # Eligibility posture (PRD §3.7)
    "ATTENDANCE_THRESHOLD_PCT": 75,
    # Volunteer screening (PRD §3.2)
    "CLEARANCE_THRESHOLD": 40,
    "RISK_FLAG_PENALTY": 10,
    "YEARS_BONUS": 2,
    "YEARS_CAP_DIVISOR": 10,
    # Star nomination quota (PRD §3.9)
    "STAR_QUOTA": 2,
    # Ownership minimums at the fair-entry deadline (PRD §3.8)
    "BEEF_MIN_OWNERSHIP_DAYS": 60,
    "SHEEP_MIN_OWNERSHIP_DAYS": 30,
    "SWINE_MIN_OWNERSHIP_DAYS": 30,
}

DEADLINES = {
    "RECORD_BOOK_DEADLINE_DATE": "2026-07-15",
    "FAIR_ENTRY_DEADLINE": "2026-08-01T00:00:00Z",
}

TEST_DEFAULTS = {
    "PROGRAM_YEAR": 2026,
    # Section scores whose provisional weighted sum is exactly 81.00
    "SCORES_81": {"completeness": 80, "accuracy": 90, "financial": 70, "reflection": 85},
    "SCORES_70": {"completeness": 70, "accuracy": 70, "financial": 70, "reflection": 70},
    "SCORES_90": {"completeness": 90, "accuracy": 90, "financial": 90, "reflection": 90},
    "SCORES_80": {"completeness": 80, "accuracy": 80, "financial": 80, "reflection": 80},
    # Clock instants relative to the 2026-07-15 record-book deadline
    "CLOCK_ON_TIME": "2026-07-10T10:00:00Z",
    "CLOCK_TWO_DAYS_LATE": "2026-07-17T10:00:00Z",
    # Volunteer registration baseline: score 50 - 0 + 3*2 = 56, always clearable
    "VOL_BASE_CLEARANCE": 50,
    "VOL_RISK_FLAGS": 0,
    "VOL_YEARS_SERVICE": 3,
}
