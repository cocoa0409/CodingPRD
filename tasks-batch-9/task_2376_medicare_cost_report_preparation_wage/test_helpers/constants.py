"""Domain thresholds and the canonical test data set.

Every numeric constant here is stated verbatim in the PRD narrative; the
canonical payload blocks are the fixed data set the composite fixtures build,
so that expected figures stay stable across the whole suite.
"""

# ---------------------------------------------------------------------------
# Numeric thresholds named in the PRD narrative
# ---------------------------------------------------------------------------

THRESHOLDS = {
    # PRD 3.5 - the wage-related cost cap is 25 percent of total salaries.
    "WAGE_RELATED_COST_CAP_PCT": 0.25,
    # PRD 3.5 - national occupational mix target percentages.
    "NATIONAL_TARGET_PCT_RN": 0.5600,
    "NATIONAL_TARGET_PCT_NURSE_AIDE": 0.2000,
    "NATIONAL_TARGET_PCT_LPN": 0.1000,
    "NATIONAL_TARGET_PCT_NURSE_PRACTITIONER": 0.1000,
    "NATIONAL_TARGET_PCT_MEDICAL_ASSISTANT": 0.0400,
    # PRD 3.5 - the occupational-mix-adjusted wage needs three staffed categories.
    "OCC_MIX_MIN_CATEGORIES": 3,
    # PRD 3.6 - initial residency period weights and the per-day FTE ceiling.
    "WITHIN_IRP_WEIGHT": 1.00,
    "BEYOND_IRP_WEIGHT": 0.50,
    "RESIDENT_DAILY_FTE_CAP": 1.0000,
    "MAX_PRIOR_PERIODS": 2,
    # PRD 3.7 - disproportionate share and uncompensated care.
    "DSH_ELIGIBILITY_THRESHOLD": 0.1500,
    "BAD_DEBT_ALLOWABLE_FACTOR": 0.65,
    "UCC_POOL_CENTS": 800_000_000_000,
    "NATIONAL_UCC_COST_CENTS": 4_000_000_000_000,
    # PRD 3.8 - the tentative settlement pays three quarters of the net.
    "TENTATIVE_PAYMENT_PCT": 0.75,
    # PRD 3.9 - interim rate gates.
    "INTERIM_VARIANCE_THRESHOLD": 0.1000,
    "INTERIM_RATE_CAP_MULTIPLIER": 1.10,
    "PRRB_MINIMUM_AMOUNT_CENTS": 1_000_000,
    # PRD 3.1 / 3.9 - calendar windows.
    "FILING_MONTHS_AFTER_FYE": 5,
    "REOPENING_WINDOW_YEARS": 3,
    "PRRB_APPEAL_WINDOW_DAYS": 180,
}

# PRD 2.3 pagination bounds.
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# PRD 2.5 - the logical clock reads this on a fresh database.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Canonical test data
# ---------------------------------------------------------------------------

CANONICAL_PROVIDER = {
    "ccn": "450123",
    "name": "Mercy General Hospital",
    "cbsa_code": "19100",
    "teaching_status": "TEACHING",
    "fte_cap": 2.00,
    "current_interim_rate_cents": 900000,
}

CANONICAL_OTHER_PROVIDER = {
    "ccn": "450999",
    "name": "Saint Elsewhere Hospital",
    "cbsa_code": "19100",
    "teaching_status": "NON_TEACHING",
    "fte_cap": 0.00,
    "current_interim_rate_cents": 0,
}

CANONICAL_COST_REPORT = {
    "fiscal_year_begin": "2025-07-01",
    "fiscal_year_end": "2026-06-30",
    "apportionment_method": "SINGLE_APPORTIONMENT",
    "medicare_utilization_ratio": 0.4000,
    "interim_payments_received_cents": 20000000,
    "total_charges_cents": 400000000,
    "medicare_discharges": 500,
}

# PRD 3.1 - a period ending 2026-06-30 carries a deadline of 2026-11-30.
CANONICAL_FILING_DEADLINE = "2026-11-30"

# PRD 3.6 - the 2025-07-01..2026-06-30 period is 365 days long.
CANONICAL_PERIOD_DAYS = 365

CANONICAL_WAGE_SUBMISSION = {
    "total_salaries_cents": 5000000000,
    "total_paid_hours": 2000000.00,
    "wage_related_costs_cents": 1500000000,
    "contract_labor_cents": 200000000,
    "contract_labor_hours": 80000.00,
    "excluded_area_salaries_cents": 100000000,
    "excluded_area_hours": 50000.00,
}

CANONICAL_OCC_MIX = [
    {"category": "RN", "reported_hours": 1200000.00, "reported_salaries_cents": 4200000000},
    {"category": "LPN", "reported_hours": 200000.00, "reported_salaries_cents": 400000000},
    {"category": "NURSE_AIDE", "reported_hours": 500000.00, "reported_salaries_cents": 750000000},
]

CANONICAL_UCC_DATA_SET = {
    "medicaid_non_medicare_days": 7495,
    "total_inpatient_days": 100000,
    "ssi_days": 7495,
    "medicare_part_a_days": 100000,
    "charity_care_charges_cents": 40000000,
    "non_medicare_bad_debt_cents": 10000000,
}
