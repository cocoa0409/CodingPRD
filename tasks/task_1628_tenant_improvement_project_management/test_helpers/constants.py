"""Domain thresholds — numeric constants from PRD calculations (sections 3.4-3.8)."""

THRESHOLDS = {
    # PRD 3.6: retainage early/late rates and the half-of-allowance tier boundary.
    "RETAINAGE_PCT_EARLY": 0.10,
    "RETAINAGE_PCT_LATE": 0.05,
    "RETAINAGE_TIER_THRESHOLD_PCT": 0.50,
    # PRD 3.5: change-order markup rate.
    "MARKUP_PCT": 0.10,
    # PRD 3.7: daily rent derivation divisor.
    "DAYS_PER_YEAR": 365,
    # PRD 3.8: invoice due-date offset in days.
    "INVOICE_DUE_DAYS": 30,
    # PRD 3.1: default cap on overlapping construction windows per property.
    "DEFAULT_MAX_CONCURRENT_CONSTRUCTION_PROJECTS": 2,
}

TEST_DEFAULTS = {
    # Standard monetary sizing used across fixtures (integer cents).
    "BASE_CONTRACT_CENTS": 40_000_000,
    "ALLOWANCE_OFFER_CENTS": 50_000_000,
    "BASE_RENT_ANNUAL_CENTS": 36_500_000,  # daily rent = exactly 100_000 cents
    "LEASE_TERM_MONTHS": 60,
    "RENTABLE_SQFT": 5_000,
    # Standard construction window used across fixtures.
    "CONSTRUCTION_START": "2026-08-03T00:00:00Z",
    "CONSTRUCTION_END": "2026-09-04T00:00:00Z",
    # Logical-clock presets.
    "CLOCK_MID_CONSTRUCTION": "2026-08-15T00:00:00Z",
    "CLOCK_CONSTRUCTION_END": "2026-09-04T00:00:00Z",
    # A draw period end safely in the past once the mid-construction clock is set.
    "PERIOD_END": "2026-08-14T00:00:00Z",
    # Insurance expiry safely beyond every clock preset used.
    "INSURANCE_EXPIRY": "2027-01-01T00:00:00Z",
    # Scheduled rent commencement used by abatement scenarios.
    "SCHEDULED_RCD": "2026-10-01T00:00:00Z",
    "SCHEDULED_RCD_ABATEMENT": "2026-09-01T00:00:00Z",
}
