"""Domain thresholds and shared literals drawn from the PRD's stated arithmetic."""

# Numeric thresholds the PRD states explicitly.
THRESHOLDS = {
    # A validated_bcr of exactly 1.000 is approvable.
    "BCR_APPROVAL_THRESHOLD": 1.0,
    # validity_end_date is effective_date plus 12 calendar months.
    "APPRAISAL_VALIDITY_MONTHS": 12,
    # A submission from RETURNED_FOR_REVISION requires revision_count to be at most 2.
    "MAX_APPRAISAL_REVISIONS": 2,
    # expires_at is presented_at plus 30 calendar days.
    "OFFER_VALIDITY_DAYS": 30,
    # next_monitoring_due_date is always an anchor date plus 36 calendar months.
    "MONITORING_INTERVAL_MONTHS": 36,
    # corrective_deadline_date is the inspection_date plus 90 calendar days.
    "CURE_WINDOW_DAYS": 90,
    # diversion_pct of at least 25.0 passes.
    "MIN_DIVERSION_PCT": 25.0,
    # viability_status reads off the rounded ratio against two inclusive lower bounds.
    "VIABILITY_VIABLE_MIN": 0.75,
    "VIABILITY_AT_RISK_MIN": 0.50,
    # buffered_start is scheduled_start minus 24 hours; buffered_end is plus 24 hours.
    "DEMOLITION_BUFFER_HOURS": 24,
    # When starting from FAILED_INSPECTION, failed_inspection_count must be at most 2.
    "MAX_DEMOLITION_REWORKS": 2,
    # replacement_housing_payment_cents is capped at 3,150,000 cents for an OWNER_OCCUPANT.
    "RHP_OWNER_CAP_CENTS": 3_150_000,
    # rental_assistance_cents is the lesser of the uncapped total and 3,150,000 cents.
    "RENTAL_ASSISTANCE_CAP_CENTS": 3_150_000,
    # rental_assistance_months is 42 when displacee_type is TENANT_90_DAY.
    "MAX_RENTAL_ASSISTANCE_MONTHS": 42,
    # The ability to pay is monthly_gross_income_cents multiplied by 0.30.
    "INCOME_RENT_RATIO": 0.30,
    # incentive_cents is capped at 2,250,000 cents.
    "INCENTIVE_CAP_CENTS": 2_250_000,
    # appeal_count must be strictly less than 2.
    "MAX_RELOCATION_APPEALS": 2,
    # The owner-occupant incentive bands, each an exclusive upper bound.
    "INCENTIVE_BAND_LOW_MAX_CENTS": 10_000_000,
    "INCENTIVE_BAND_MID_MAX_CENTS": 25_000_000,
    # discount_rate_pct defaults to 0.07 and is read as a rate, not as a percent.
    "DEFAULT_DISCOUNT_RATE": 0.07,
    "INCENTIVE_RATE_LOW": 0.10,
    "INCENTIVE_RATE_MID": 0.07,
    "INCENTIVE_RATE_HIGH": 0.05,
}

# The duplication-of-benefits factor per benefit_source.
DOB_FACTORS = {
    "NFIP_CLAIM": 1.00,
    "ICC": 1.00,
    "PRIVATE_INSURANCE": 1.00,
    "SBA_LOAN": 0.50,
    "CDBG_DR": 0.85,
}

# A termination reference must begin with this literal prefix.
OPEN_SPACE_TERMINATION_AUTH_PREFIX = "FEMA-OSR-"

# The four utility types copied onto every work order as required_utility_types.
REQUIRED_UTILITY_TYPES = ["WATER", "ELECTRIC", "GAS", "SEWER"]

# The four codes copied onto every restriction as prohibited_uses.
PROHIBITED_USE_CODES = [
    "NEW_STRUCTURE",
    "FILL_PLACEMENT",
    "RESALE_FOR_DEVELOPMENT",
    "PERMANENT_STORAGE",
]

# On a cold service the logical clock stands at this instant.
DEFAULT_LOGICAL_CLOCK_UTC = "2026-08-01T00:00:00Z"
DEFAULT_LOGICAL_CLOCK_DATE = "2026-08-01"

# Reusable literals for setup payloads.
TEST_DEFAULTS = {
    "SUBRECIPIENT_NAME": "City of Riverbend",
    "GRANT_PROGRAM": "FMA",
    "COST_SHARE_FEDERAL_PCT": 0.75,
    "LARGE_CAP_CENTS": 500_000_000,
    "PERIOD_OF_PERFORMANCE_END_DATE": "2028-12-31",
    "PRE_EVENT_FMV_CENTS": 20_000_000,
    "APPRAISAL_EFFECTIVE_DATE": "2026-07-01",
    "REVIEW_APPRAISAL_EFFECTIVE_DATE": "2026-07-05",
    "VOLUNTARY_SIGNED_ON": "2026-08-01",
}
