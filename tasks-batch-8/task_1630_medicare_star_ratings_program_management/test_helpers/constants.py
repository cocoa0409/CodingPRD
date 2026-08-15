"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Survey sufficiency: response_rate >= 0.40 is sufficient (exactly 0.40 counts)
    "SURVEY_MIN_RESPONSE_RATE": 0.40,
    # Complaint timeliness SLA in days (strictly greater than 30 is late)
    "COMPLAINT_SLA_DAYS": 30,
    # Care gap intervention cap
    "INTERVENTION_CAP": 3,
    # Improvement pseudo-measure weight in the weighted average
    "IMPROVEMENT_WEIGHT": 5,
    # Improvement score band boundaries
    "IMPROVEMENT_BAND_5_MIN": 0.20,
    "IMPROVEMENT_BAND_4_MIN": 0.08,
    "IMPROVEMENT_BAND_2_MAX": -0.08,
    "IMPROVEMENT_BAND_1_MAX": -0.20,
    # Rebate tier rates keyed on (projected or official) overall stars
    "REBATE_TIER_35": 0.035,
    "REBATE_TIER_40": 0.040,
    "REBATE_TIER_45": 0.045,
    "REBATE_TIER_50": 0.050,
    "REBATE_TIER_FLOOR_STARS": 3.5,
}

PRECISION = {
    "RAW_VALUE_DP": 2,
    "IMPROVEMENT_SCORE_DP": 4,
    "RESPONSE_RATE_DP": 4,
    "DOLLAR_DP": 2,
}

TEST_DEFAULTS = {
    "MEASUREMENT_YEAR": 2026,
    "RATING_YEAR": 2028,
    "BENCHMARK_PMPM": 950.0,
    "PLAN_CONTRACT": "H1234",
    "ENROLLED_MONTHS": 12,
    # Logical clock startup default (PRD section 2.4)
    "CLOCK_START": "2026-08-01T00:00:00Z",
}
