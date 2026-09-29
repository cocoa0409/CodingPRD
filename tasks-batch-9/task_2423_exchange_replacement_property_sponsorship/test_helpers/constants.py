"""Domain thresholds and pinned numeric constants from the PRD's calculations."""

# --------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# --------------------------------------------------------------------------
CLOCK_STARTUP = "2026-08-01T00:00:00Z"


# --------------------------------------------------------------------------
# Declared thresholds
# --------------------------------------------------------------------------
THRESHOLDS = {
    # Loan credit tests, expressed in the PRD's integer cross-multiplication form.
    "LTV_MAX_BPS": 7500,
    "DSCR_MIN_BPS": 12500,
    # Depreciation recovery period, in years.
    "DEPRECIATION_YEARS": 39,
    # Land is excluded as twenty percent of the purchase price.
    "DEPRECIABLE_SHARE_PCT": 80,
    # Exchange clocks, in days from the relinquished closing date.
    "IDENTIFICATION_WINDOW_DAYS": 45,
    "EXCHANGE_WINDOW_DAYS": 180,
    # Accreditation verification life, in days.
    "ACCREDITATION_VALID_DAYS": 90,
    # Identification rule limits.
    "THREE_PROPERTY_MAX_ROWS": 3,
    "TWO_HUNDRED_PCT_MULTIPLIER": 200,
    # Suitability concentration bands, in percent of liquid net worth.
    "LIQUIDITY_BAND_PCT": {
        "IRA": 10,
        "INDIVIDUAL": 25,
        "JOINT": 25,
        "LLC": 35,
        "REVOCABLE_TRUST": 35,
    },
    "MEANS_INCOME_MULTIPLE": 3,
    "MEANS_NET_WORTH_PCT": 30,
    "DEAL_CAP_PCT": 60,
    # Accrual proration denominator.
    "DAYS_PER_YEAR": 365,
}


# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}


# --------------------------------------------------------------------------
# The canonical deal used throughout the suite.
#
# Property "Cypress Logistics Center" at 12,000,000.00 held by a 620-unit
# trust, financed with a 7,200,000.00 non-recourse facility at 425 bps, and
# offered at 10,000.00 per unit with a 9% load.
# --------------------------------------------------------------------------
TEST_DEFAULTS = {
    "PROPERTY_NAME": "Cypress Logistics Center",
    "PROPERTY_STATE_CODE": "TX",
    "PROPERTY_ASSET_TYPE": "INDUSTRIAL",
    "PURCHASE_PRICE_CENTS": 1_200_000_000,
    "APPRAISED_VALUE_CENTS": 1_200_000_000,
    "ANNUAL_NOI_CENTS": 97_000_000,
    "OCCUPANCY_RATE": 0.95,
    "CONTRACT_CLOSE_DEADLINE": "2026-09-30T23:59:59.999Z",
    "TRUST_NAME": "DST 2423-A Cypress",
    "TOTAL_UNITS": 620,
    "RESERVE_FLOOR_CENTS": 5_000_000,
    "RESERVE_TARGET_PCT": 0.02,
    "UNIT_PRICE_CENTS": 1_000_000,
    "MIN_UNITS_PER_INVESTOR": 15,
    "LOAD_PCT": 0.09,
    "CLOSING_COSTS_CENTS": 35_000_000,
    "RESERVE_FUNDING_PCT": 0.025,
    "RESCISSION_WINDOW_DAYS": 5,
    "LOAN_LENDER_NAME": "Gulf Coast Life",
    "LOAN_PRINCIPAL_CENTS": 720_000_000,
    "LOAN_RATE_BPS": 425,
    "LOAN_MATURITY_ON": "2033-08-01",
    "MASTER_TENANT_USER_ID": "tenant-1",
    "LEASE_TERM_START_ON": "2026-09-01",
    "LEASE_TERM_END_ON": "2033-08-31",
    "LEASE_BASE_RENT_ANNUAL_CENTS": 90_000_000,
    "LEASE_SUPPLEMENTAL_RENT_ANNUAL_CENTS": 1_500_000,
}


# --------------------------------------------------------------------------
# Figures the PRD's formulas force for the canonical deal. Pinned so tests
# assert against the contract rather than against a re-derivation.
# --------------------------------------------------------------------------
CANONICAL_CAPITAL_STACK = {
    "initial_reserve_cents": 30_000_000,
    "net_acquisition_cents": 515_000_000,
    "base_need_cents": 545_000_000,
    "target_equity_cents": 598_901_099,
    "sponsor_load_cents": 53_901_099,
    "unit_capacity_cents": 620_000_000,
}

CANONICAL_LOAN_METRICS = {
    "ltv_pct": 60.0,
    "dscr": 3.1699,
}

CANONICAL_OPERATING_TRUST = {
    "units_issued": 600,
    "equity_raised_cents": 600_000_000,
    "operating_balance_cents": 1_098_901,
    "reserve_balance_cents": 30_000_000,
}

# The 2026-10-01 -> 2027-01-01 quarter, measured twice, for a trust that took
# 22,500,000 of base rent and 375,000 of supplemental rent on 2026-12-01 and
# paid 7,650,000 of debt service on 2026-12-15.
CANONICAL_DISTRIBUTION = {
    "period_start": "2026-10-01T00:00:00Z",
    "period_end": "2027-01-01T00:00:00Z",
    "reserve_replenishment_cents": 453_699,
    "provisional_amount_cents": 14_896_438,
    "final_amount_cents": 14_771_301,
    "reconciliation_delta_cents": -125_137,
    "reserve_balance_after_pay_cents": 30_453_699,
}

CANONICAL_ALLOCATION = {
    "raw_share_cents": 7_385_650.5,
    "subscription_a_allocated_cents": 7_385_650,
    "subscription_a_residual_adjustment_cents": -1,
    "subscription_b_allocated_cents": 7_385_651,
    "subscription_b_residual_adjustment_cents": 0,
}

# Grantor-trust totals for tax year 2026 on the canonical deal, under the two
# elected conventions, for the subscription that closed on 2026-09-15.
CANONICAL_TAX_STATEMENT = {
    "UNITS_AT_YEAR_END": {
        "rental_income_cents": 11_437_500,
        "interest_expense_cents": 3_825_000,
        "depreciation_cents": 4_518_441,
        "net_taxable_income_cents": 3_094_059,
    },
    "UNIT_DAYS_WEIGHTED": {
        "rental_income_cents": 16_470_000,
        "interest_expense_cents": 5_508_000,
        "depreciation_cents": 6_506_554,
        "net_taxable_income_cents": 4_455_446,
    },
}

CANONICAL_DEPRECIABLE_BASIS_CENTS = 960_000_000
