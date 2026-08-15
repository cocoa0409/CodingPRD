"""Domain thresholds and numeric constants from the PRD's calculation rules."""

# Logical clock startup default (PRD 2.4).
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Retainage / certification constants (PRD 3.5).
RETAINAGE_HIGH_PCT = 0.10
RETAINAGE_LOW_PCT = 0.05
RETAINAGE_HALFWAY_PCT = 0.50
STORED_MATERIALS_PCT = 0.10

# Change-order pricing tiers (PRD 3.6).
MARKUP_TIER1_CAP_CENTS = 5000000
MARKUP_TIER2_CAP_CENTS = 5000000
MARKUP_TIER1_PCT = 0.10
MARKUP_TIER2_PCT = 0.07
MARKUP_TIER3_PCT = 0.04

# Whole-month billing (PRD 3.8).
MONTH_DAYS = 30

# Default review/issuance windows (PRD 3.1).
DEFAULT_GRACE_DAYS = 0
DEFAULT_REVIEW_WINDOW_DAYS_SUBMITTAL = 10
DEFAULT_REVIEW_WINDOW_DAYS_RFI = 7
DEFAULT_FIELD_REPORT_WINDOW_DAYS = 3

# Pagination defaults (PRD 2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Recurring opaque user identifiers used across fixtures.
USER_OWNER = "user-owner-1"
USER_CONTRACTOR = "user-contractor-1"
USER_ARCH_LEAD = "user-arch-lead"
USER_ARCH_2 = "user-arch-2"
USER_ARCH_3 = "user-arch-3"
USER_FIRM_ADMIN = "user-firm-admin-1"

TEST_DEFAULTS = {
    "ORIGINAL_CONTRACT_SUM_CENTS": 10000000,
    "DAILY_EXTENSION_RATE_CENTS": 120000,
    "MONTHLY_EXTENSION_RATE_CENTS": 3000000,
    "BASE_SCD": "2026-09-30",
}
