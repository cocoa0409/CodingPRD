"""Domain thresholds and defaults taken from the PRD's calculation rules."""

# The logical clock reads this instant at server startup.
CLOCK_START_UTC = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # red-flag detection
    "SEVERE_LOSS_DB": 71.0,
    "ASYMMETRY_DB": 15.0,
    "ADVISORY_REFERRAL_THRESHOLD": 2.5,
    # candidacy risk score
    "W_PTN": 0.40,
    "W_DIFF": 0.25,
    "W_SIN": 0.20,
    "W_ASYM": 0.15,
    "PROVIDER_ATTENUATION": 0.85,
    "MANDATORY_FLAG_POINTS": 6.0,
    "ADVISORY_POINT_FACTOR": 2.0,
    "BAND_MODERATE_MIN": 35.0,
    "BAND_HIGH_MIN": 65.0,
    # order totals
    "SALES_TAX_RATE": 0.0725,
    # trial clock
    "SECONDS_PER_DAY": 86400,
    "MAX_TOTAL_PAUSED_DAYS": 60,
    # return settlement
    "ACCESSORY_RATE_FACTOR": 0.5,
    "DAMAGE_RATE": 0.15,
    "REFURB_RATE": 0.05,
    # reimbursement
    "REPAIR_ELIGIBLE_CAP_CENTS": 50000,
    "CARE_PLAN_ELIGIBLE_CYCLES": 12,
    # care plan billing
    "PREMIUM_SURCHARGE_CENTS": 2000,
    "SERVICE_FEE_CENTS": 495,
    "SERVICE_FEE_WAIVER_THRESHOLD_CENTS": 9900,
    "LOYALTY_TIER1_CYCLES": 6,
    "LOYALTY_TIER1_RATE": 0.10,
    "LOYALTY_TIER2_CYCLES": 12,
    "LOYALTY_TIER2_RATE": 0.15,
    "LOYALTY_DISCOUNT_CAP_CENTS": 1500,
    # warranty deductible
    "BASE_DEDUCTIBLE_CENTS": 9900,
    "AGE_TIER1_MONTHS": 12,
    "AGE_TIER1_MULT": 0.5,
    "AGE_TIER2_MONTHS": 24,
    "AGE_TIER2_MULT": 1.0,
    "AGE_TIER3_MULT": 1.5,
    "SECOND_CLAIM_SURCHARGE_CENTS": 5000,
    # fit exchange
    "FREE_EXCHANGE_COUNT": 2,
    "EXCHANGE_FEE_CENTS": 1900,
    "PREMIUM_DISCOUNT_FACTOR": 0.5,
    # repair SLA credit
    "SLA_CREDIT_PER_DAY_CENTS": 500,
    "SLA_CREDIT_CAP_CENTS": 5000,
    "PREMIUM_CREDIT_MULT": 2.0,
    # warranty term
    "WARRANTY_DAYS": 730,
    # return shipment window
    "RETURN_DEADLINE_DAYS": 14,
    # limits
    "MAX_RESCHEDULES": 3,
    "MAX_INFO_REQUESTS": 3,
    "MAX_DUNNING_ATTEMPTS": 3,
    "MAX_INSTALL_ATTEMPTS": 3,
    "CAMPAIGN_RESUME_FAILURE_CEILING_PCT": 25.0,
}

PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

TEST_DEFAULTS = {
    # the canonical CA policy used across the suite
    "STATE_CODE": "CA",
    "TRIAL_PERIOD_DAYS": 45,
    "RESTOCKING_FEE_PCT": 0.1,
    "REFERRAL_VALIDITY_DAYS": 180,
    "MAX_LOSS_DAMAGE_CLAIMS": 2,
    "MIN_AGE_YEARS": 18,
    # canonical order economics
    "LIST_PRICE_CENTS": 199900,
    "DISCOUNT_CENTS": 9900,
    "ACCESSORY_SUBTOTAL_CENTS": 4500,
    "SHIPPING_CENTS": 1495,
    # canonical device / pool
    "MODEL": "NEO",
    "DOME_SIZE": "M",
    "TIP_TYPE": "OPEN",
    "FIRMWARE_VERSION": "4.0.0",
    # canonical provider
    "DAILY_CAPACITY_MINUTES": 240,
    "BUFFER_MINUTES": 10,
    # canonical care plan
    "PLAN_TIER": "STANDARD",
    "BASE_FEE_CENTS": 4900,
}
