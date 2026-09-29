"""Domain thresholds and shared numeric constants drawn from the PRD."""

# The logical clock reads exactly this instant before any client sets it.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Concentration screen
    "HHI_POST_THRESHOLD_MSA": 1800,
    "HHI_POST_THRESHOLD_RURAL_COUNTY": 2200,
    "HHI_DELTA_SAFE_HARBOR": 200,
    "HHI_PRESUMPTION_LEVEL": 2500,
    "HHI_PRESUMPTION_DELTA": 400,
    "DIVESTITURE_SEARCH_STEP_USD": 1_000_000,
    # Management composite banding
    "MANAGEMENT_SATISFACTORY_MIN": 70.00,
    "MANAGEMENT_CONDITIONAL_MIN": 55.00,
    # Capital adequacy banding
    "WELL_CAPITALIZED_CET1_PCT": 7.00,
    "WELL_CAPITALIZED_LEVERAGE_PCT": 5.00,
    "ADEQUATELY_CAPITALIZED_CET1_PCT": 4.50,
    "ADEQUATELY_CAPITALIZED_LEVERAGE_PCT": 4.00,
    # Comment window
    "DEFAULT_COMMENT_DURATION_DAYS": 30,
    "COMMENT_GRACE_TAIL_DAYS": 3,
    "POST_COMMENT_REVIEW_DAYS": 15,
    "HEARING_EXTENSION_DAYS": 30,
    # Branch closure and conversion
    "CLOSURE_NOTICE_MIN_LEAD_DAYS": 90,
    "CONVERSION_BUFFER_DAYS": 15,
    "DISCLOSURE_MIN_LEAD_DAYS": 30,
    # Waiting period
    "BASE_WAITING_DAYS_HOLDCO": 30,
    "BASE_WAITING_DAYS_BANK_LEVEL": 15,
    "HEARING_GRANTED_ADDITION_DAYS": 15,
    "UNRESOLVED_PROTEST_ADDITION_DAYS": 10,
    "EXPEDITED_REDUCTION_DAYS": 10,
    "WAITING_PERIOD_FLOOR_DAYS": 5,
    "CONSUMMATION_WINDOW_DAYS": 180,
    # Post-closing monitoring
    "REPORT_ACCEPTANCE_FULFILLMENT_PCT": 90.00,
    "CONSECUTIVE_DEFICIENT_BREACH": 2,
    "QUARTERS_PER_YEAR": 4,
}

# Balance-sheet figures used by the canonical two-institution world.
NORTHBAY_CAPITAL = {
    "cet1_capital_usd": 200_000_000,
    "tier1_capital_usd": 210_000_000,
    "total_capital_usd": 240_000_000,
    "risk_weighted_assets_usd": 2_000_000_000,
    "average_total_assets_usd": 2_600_000_000,
    "total_loans_usd": 1_500_000_000,
}

HARBOR_CAPITAL = {
    "cet1_capital_usd": 60_000_000,
    "tier1_capital_usd": 62_000_000,
    "total_capital_usd": 70_000_000,
    "risk_weighted_assets_usd": 700_000_000,
    "average_total_assets_usd": 800_000_000,
    "total_loans_usd": 520_000_000,
}

LAKESIDE_CAPITAL = {
    "cet1_capital_usd": 500_000_000,
    "tier1_capital_usd": 520_000_000,
    "total_capital_usd": 560_000_000,
    "risk_weighted_assets_usd": 4_000_000_000,
    "average_total_assets_usd": 5_000_000_000,
    "total_loans_usd": 3_000_000_000,
}

# The purchase-accounting adjustment set that yields a WELL_CAPITALIZED
# REGULATORY_ADJUSTED schedule for the Northbay/Harbor pair.
WELL_CAPITALIZED_ADJUSTMENTS = {
    "goodwill_created_usd": 40_000_000,
    "core_deposit_intangible_usd": 10_000_000,
    "aoci_markdown_usd": 25_000_000,
    "deferred_tax_asset_usd": 12_000_000,
    "transaction_costs_usd": 5_000_000,
    "cash_consideration_usd": 20_000_000,
}

# The adjustment set that drives the same pair UNDERCAPITALIZED.
UNDERCAPITALIZED_ADJUSTMENTS = {
    "goodwill_created_usd": 180_000_000,
    "core_deposit_intangible_usd": 30_000_000,
    "aoci_markdown_usd": 25_000_000,
    "deferred_tax_asset_usd": 40_000_000,
    "transaction_costs_usd": 8_000_000,
    "cash_consideration_usd": 60_000_000,
}

# Examiner scores 72/68/67/73 give a management_composite_score of 70.11.
STANDARD_EXAMINER_SCORES = {
    "officer_experience_score": 72,
    "risk_management_score": 68,
    "compliance_history_score": 67,
    "integration_readiness_score": 73,
}

# The canonical four-category commitment package: 392,000,000 total.
STANDARD_LINE_ITEMS = [
    ("MORTGAGE_LENDING", 250_000_000),
    ("SMALL_BUSINESS_LENDING", 120_000_000),
    ("PHILANTHROPY", 7_000_000),
    ("CDFI_INVESTMENT", 15_000_000),
]
