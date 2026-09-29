"""Numeric thresholds and shared test defaults drawn from the PRD."""
from __future__ import annotations

THRESHOLDS: dict[str, object] = {
    # Renewal window (§ Opening a Renewal Case): strictly greater than zero and at most 420 days.
    "RENEWAL_WINDOW_MAX_DAYS": 420,
    "RENEWAL_WINDOW_MIN_DAYS_EXCLUSIVE": 0,
    # Operating-cost adjustment factors by state code.
    "OCAF_FACTOR_IL": "1.032",
    "OCAF_FACTOR_TX": "1.028",
    # Budget-based management fee.
    "MANAGEMENT_FEE_RATE": "0.08",
    # Comparability studies.
    "MAX_CHALLENGE_ROUNDS": 3,
    "COMPARABLE_WEIGHT_MIN": 1,
    "COMPARABLE_WEIGHT_MAX": 5,
    "COMPARABLE_ROUNDING_UNIT_CENTS": 100,
    # Rent ceilings on approval.
    "BUDGET_RENT_CAP_MULTIPLIER": "1.10",
    # Restructuring.
    "FMR_FLOOR_MULTIPLIER": "1.00",
    "M2M_HAIRCUT_MULTIPLIER": "0.90",
    # Statutory notice lead days by notice type.
    "REQUIRED_LEAD_DAYS_RENEWAL_INTENT": 120,
    "REQUIRED_LEAD_DAYS_OPT_OUT_ONE_YEAR": 365,
    "REQUIRED_LEAD_DAYS_TERMINATION_120_DAY": 120,
    "REQUIRED_LEAD_DAYS_RENT_CHANGE": 30,
    # Total tenant payment.
    "TTP_ADJUSTED_INCOME_RATE": "0.30",
    "TTP_GROSS_INCOME_RATE": "0.10",
    "MINIMUM_RENT_CENTS": 2500,
    # Utility allowance analyses.
    "UA_FIELD_OFFICE_THRESHOLD_PCT": "0.10",
    "UA_RATE_CHANGE_MIN": "-0.5",
    "UA_RATE_CHANGE_MAX": "0.5",
    "UA_INTERVAL_MONTHS": 12,
    "CHANGE_PCT_DECIMAL_PLACES": 4,
    # Certification spacing: strictly more than 30 days.
    "CERT_SPACING_DAYS_EXCLUSIVE": 30,
    # Special claims.
    "VACANCY_DAYS_CAP": 60,
    "PROJECTED_ESTIMATE_RATE": "0.80",
    "PROJECTED_ESTIMATE_MONTH_DAYS": 30,
    "UNPAID_RENT_CAP_MONTHS": 1,
    "TENANT_DAMAGES_CAP_MONTHS": 2,
    # Pagination.
    "PAGINATION_DEFAULT_LIMIT": 10,
    "PAGINATION_MIN_LIMIT": 1,
    "PAGINATION_MAX_LIMIT": 100,
    "PAGINATION_DEFAULT_OFFSET": 0,
}

TEST_DEFAULTS: dict[str, object] = {
    # The logical clock begins at this instant on a freshly started server.
    "CLOCK_START": "2026-08-01T00:00:00Z",
    "CLOCK_START_DATE": "2026-08-01",
    # Shared reference portfolio used across the suite.
    "OWNER_LEGAL_NAME": "Cedar Ridge Housing Partners LP",
    "OWNER_TIN": "27-3310011",
    "OWNER_CONTACT_EMAIL": "agent@cedarridge.example",
    "PROJECT_NAME": "Cedar Ridge Apartments",
    "STATE_CODE": "IL",
    "TOTAL_UNITS": 24,
    "ASSISTED_UNIT_COUNT": 20,
    "PUBLISHED_FMR_CENTS": 126000,
    "BASELINE_UTILITY_ALLOWANCE_CENTS": 11500,
    "CONTRACT_TYPE": "NEW_CONSTRUCTION",
    "EXPIRATION_DATE": "2027-12-31",
    "TERM_MONTHS": 12,
    "CONTRACT_RENT_PER_UNIT_CENTS": 118000,
    "MONTHLY_DEBT_SERVICE_PER_UNIT_CENTS": 32000,
    "OPERATING_EXPENSE_PER_UNIT_CENTS": 61000,
    "RESERVE_DEPOSIT_PER_UNIT_CENTS": 4500,
    "AUTHORIZED_HAP_BUDGET_CENTS": 30000000,
    "APPRAISER_NAME": "Hollis Appraisal Group",
}
