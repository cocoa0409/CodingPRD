"""Domain thresholds and numeric constants stated by the PRD."""

# The logical clock's documented startup value (PRD §2.5).
CLOCK_START_UTC = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Rooms are occupied as a closed interval expanded by 15 minutes on the end
    # side only, so turnover time is protected.
    "ROOM_TURNOVER_BUFFER_MIN": 15,
    # A session may be started at most 15 minutes before its scheduled start.
    "SESSION_START_GRACE_MIN": 15,
    # Sessions starting inside this window are cancelled by facility/coverage rules.
    "SESSION_LOCK_WINDOW_HOURS": 24,
    # A cleanliness score at or above 85 with zero deficiencies passes.
    "ROOM_PASS_SCORE": 85,
    # VERIFIED -> EXPIRING_SOON lead time.
    "CREDENTIAL_EXPIRING_WINDOW_DAYS": 30,
    # An offering may only be activated when the lead's readiness index is >= 70.
    "ACTIVATION_MIN_READINESS": 70,
    # Cohorts strictly below 5 distinct participants are suppressed in the report.
    "PRIVACY_MIN_COHORT": 5,
    # A defibrillator inspected more than 30 days ago is NOT_READY.
    "AED_INSPECTION_MAX_AGE_DAYS": 30,
    # Consumables expiring within 30 days downgrade a ready unit to PADS_EXPIRING.
    "AED_PADS_WARNING_DAYS": 30,
    # A LEAD assignment is paid the session minutes plus a 15-minute setup allowance.
    "LEAD_SETUP_MIN": 15,
    # Readiness drill-recency bands, in days.
    "DRILL_FRESH_DAYS": 90,
    "DRILL_STALE_DAYS": 180,
    # Workload headroom soft cap, in minutes (100 hours).
    "WORKLOAD_SOFT_CAP_MINUTES": 6000,
    "WORKLOAD_PENALTY_PER_HOUR": 5,
    # Incentive award parameters.
    "BASE_POINTS": 10,
    "STREAK_BONUS_POINTS": 5,
    "STREAK_MIN_PRIOR_DAYS": 3,
    "WEEKLY_POINTS_CAP": 60,
    # Equipment downtime credit.
    "DOWNTIME_GRACE_DAYS": 3,
    "DOWNTIME_RATE_AED_CENTS_PER_DAY": 1200,
    "DOWNTIME_RATE_OTHER_CENTS_PER_DAY": 250,
    # Coverage shortfall penalty on management-fee contracts.
    "COVERAGE_ALLOWANCE_SESSIONS": 1,
    "COVERAGE_PENALTY_RATE_PCT": 1.5,
    "COVERAGE_PENALTY_CEILING_RATE_PCT": 5.0,
    # Cost-plus administrative markup ladder, keyed on the base.
    "MARKUP_TIER1_MAX_BASE": 15000,
    "MARKUP_TIER1_RATE_PCT": 12,
    "MARKUP_TIER2_MAX_BASE": 30000,
    "MARKUP_TIER2_RATE_PCT": 9,
    "MARKUP_TIER3_RATE_PCT": 7,
    # Volume credit ladder, keyed on the gross.
    "VOLUME_CREDIT_HIGH_GROSS": 70000,
    "VOLUME_CREDIT_HIGH_RATE_PCT": 3.0,
    "VOLUME_CREDIT_LOW_GROSS": 35000,
    "VOLUME_CREDIT_LOW_RATE_PCT": 1.5,
    # Pagination bounds.
    "PAGINATION_DEFAULT_LIMIT": 10,
    "PAGINATION_MIN_LIMIT": 1,
    "PAGINATION_MAX_LIMIT": 100,
}

REQUIRED_CREDENTIALS_BY_ROLE = {
    "SITE_MANAGER": ["CPR_AED"],
    "GROUP_EX_INSTRUCTOR": ["GROUP_EX_CERT"],
    "PERSONAL_TRAINER": ["PT_CERT"],
    "WELLNESS_COORDINATOR": ["FIRST_AID"],
}

TEST_DEFAULTS = {
    "MANAGEMENT_FEE_CENTS": 40000,
    "NOT_TO_EXCEED_CENTS": 5_000_000,
    "INSTRUCTOR_HOURLY_COST_CENTS": 4700,
    "MANAGER_HOURLY_COST_CENTS": 5200,
    "TERM_START_ON": "2026-07-01",
    "TERM_END_ON": "2027-06-30",
    "CREDENTIAL_EXPIRES_ON": "2027-05-31",
    "DRILL_ON": "2026-07-15",
    "WAIVER_EXPIRES_ON": "2027-07-31",
    "AED_PAD_EXPIRY_ON": "2027-03-31",
    "AED_BATTERY_EXPIRY_ON": "2027-03-31",
    "AED_LAST_INSPECTION_ON": "2026-07-20",
}

# An identifier that is not a UUID at all — a shape violation, distinct from a
# well-formed identifier that simply matches no row.
MALFORMED_ID = "not-a-uuid"
