"""Domain thresholds and interval lengths stated by the PRD."""

# The logical clock the API starts on, and the instants the suite pins it to.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
CLOCK_PLUS_180 = "2027-01-28T00:00:00Z"   # activation deadline for a block reserved at DEFAULT_CLOCK
CLOCK_PLUS_181 = "2027-01-29T00:00:00Z"   # first instant a sweep reclaims that block
CLOCK_PLUS_30 = "2026-08-31T00:00:00Z"    # 30-day comment window close / reclamation response due

INTERVALS = {
    "ACTIVATION_WINDOW_DAYS": 180,
    "RECLAMATION_RESPONSE_DAYS": 30,
    "AGING_PERIOD_DAYS": 90,
    "PROBATION_DAYS": 180,
    "PERMISSIVE_DIALING_DAYS": 180,
    "RELIEF_BUFFER_DAYS": 90,
    "DEFAULT_COMMENT_WINDOW_DAYS": 30,
}

THRESHOLDS = {
    # Exhaust posture
    "JEOPARDY_AVAILABLE_BLOCKS": 4,          # 4 or fewer available blocks is jeopardy
    "EXHAUST_SENTINEL_MONTHS": 999.00,
    "MONTHS_TO_EXHAUST_MAX": 6,
    # Pooling
    "CONTAMINATION_CEILING": 100,            # <= 100 contaminated numbers is pooling eligible
    "MAX_CONTAMINATED_COUNT": 1000,
    # Allocation entitlement tiers, keyed on effective utilization percentage
    "TIER_CAP_3_MIN_PCT": 90.00,
    "TIER_CAP_2_MIN_PCT": 75.00,
    "TIER_CAP_1_MIN_PCT": 60.00,
    "NUMBERS_PER_BLOCK": 1000,
    "SAFETY_VALVE_MAX_BLOCKS": 1,
    "SAFETY_VALVE_MAX_GRANTS": 1,
    "INFO_CYCLE_MAX": 2,
    "MAX_REQUESTED_BLOCK_COUNT": 10,
    # Audit penalties, both bounds inclusive
    "RECLAMATION_REFERRAL_DELTA_PCT": 20.00,
    "PROBATION_DELTA_PCT": 5.00,
    "STRIKES_FOR_PROBATION": 2,
    # Reclamation sweep
    "UTILIZATION_SHORTFALL_PCT": 60.00,
}

# Donation obligation rate, keyed on the holder's pre-donation utilization.
DONATION_RATES = {
    "AT_OR_ABOVE_90": 0.00,
    "AT_OR_ABOVE_75": 0.10,
    "AT_OR_ABOVE_60": 0.25,
    "BELOW_60": 0.50,
}

# Public comment weights by commenter_type.
COMMENT_WEIGHTS = {
    "CONSUMER": 1.0,
    "BUSINESS": 1.5,
    "CARRIER": 2.0,
    "GOVERNMENT": 3.0,
}

# Values reused across the suite so fixtures and tests agree on the scenario.
TEST_DEFAULTS = {
    "NPA_CODE": "614",
    "STATE_CODE": "OH",
    "LATA_CODE": "324",
    "RATE_CENTER_NAME": "COLUMBUS",
    "SIBLING_RATE_CENTER_NAME": "DUBLIN",
    "LICENSE_EXPIRES_ON": "2028-08-01T00:00:00Z",
    "SWITCH_CLLI_A": "CLMBOH01DS0",
    "SWITCH_CLLI_B": "CLMBOH02DS0",
    "SWITCH_CLLI_C": "CLMBOH03DS0",
    "REPORTING_PERIOD": "2026-H1",
    "PRIOR_REPORTING_PERIOD": "2025-H2",
    "NEXT_REPORTING_PERIOD": "2026-H2",
}

# A syntactically valid identifier that names nothing.
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"
