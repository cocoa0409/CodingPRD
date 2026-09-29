"""Domain thresholds and defaults drawn from the PRD's stated numbers."""

# Numeric policy constants named by the PRD.
THRESHOLDS = {
    # Benefit valuation (PRD: benefits worth 2 percent of the recurring
    # contribution or less are insubstantial, capped at 130 dollars).
    "INSUBSTANTIAL_PCT_BPS": 200,
    "INSUBSTANTIAL_CAP_CENTS": 13000,
    "MAX_BENEFITS_PER_TIER": 8,
    "DEFAULT_GRACE_PERIOD_DAYS": 30,
    "MIN_CONTRIBUTION_AMOUNT_CENTS": 100,
    # Membership giving.
    "MAJOR_DONOR_THRESHOLD_CENTS": 500000,
    # Gift stewardship netting.
    "FEE_TIER_1_FLOOR_CENTS": 1000000,
    "FEE_TIER_2_FLOOR_CENTS": 5000000,
    "FEE_TIER_1_BPS": 150,
    "FEE_TIER_2_BPS": 250,
    "BOARD_RATIFICATION_THRESHOLD_CENTS": 2500000,
    "RATIFICATION_RISK_FLOOR": 40,
    "MIN_MAJOR_GIFT_CENTS": 100000,
    "MAX_CONDITION_ROUNDS": 2,
    # Independence risk scoring.
    "TYPE_WEIGHT_FOUNDATION": 10,
    "TYPE_WEIGHT_INDIVIDUAL": 5,
    "TYPE_WEIGHT_CORPORATE": 25,
    "TYPE_WEIGHT_GOVERNMENT": 20,
    "ADVOCACY_WEIGHT": 4,
    "EDITORIAL_REQUEST_WEIGHT": 8,
    "AFFILIATION_WEIGHT": 10,
    "RELIABILITY_WEIGHT": 25,
    "RELIABILITY_PENALTY_BPS": 2000,
    "SELF_ATTESTED_ADVOCACY_INDEX": 3,
    "RISK_DISCLOSURE_FLOOR": 40,
    "RISK_HARD_BAR": 60,
    "RISK_SCORE_CAP": 100,
    "MAX_AUDITED_ADVOCACY_INDEX": 10,
    "COOLING_OFF_DAYS": 30,
    # Grant pipeline.
    "MAX_REVISION_ROUNDS": 3,
    "MAX_RESTRICTED_GRANTS_PER_AREA": 2,
    "MIN_REQUESTED_AMOUNT_CENTS": 100000,
    "DEFAULT_AWARD_PROBABILITY_BPS": 5000,
    "REPORT_GRACE_DAYS": 45,
    "MAX_ACCEPTABLE_VARIANCE_BPS": 2000,
    # Reserve policy.
    "RESERVE_MONTHS_BASE": 3,
    "HHI_ESCALATION_1": 3000,
    "TOP_SOURCE_ESCALATION": 3500,
    "HHI_WATCH": 4000,
    "CONCENTRATION_BOARD_FLOOR_HHI": 4500,
    "RESERVE_FLOOR_RATIO_BPS": 10000,
    "RELEASE_CAP_BPS_HEALTHY": 10000,
    "RELEASE_CAP_BPS_WATCH": 6000,
    "RELEASE_CAP_BPS_CONSTRAINED": 2500,
    "RELEASE_CAP_BPS_CRITICAL": 0,
    # Basis points and pagination.
    "BPS_TOTAL": 10000,
    "DEFAULT_LIMIT": 10,
    "MAX_LIMIT": 100,
}

# The logical clock's value on a fresh server.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"
CLOCK_EPOCH_TIMESTAMP = "2026-08-01T00:00:00.000Z"

# Values reused by fixtures and tests as the "ordinary" scenario.
TEST_DEFAULTS = {
    "PERIOD_LABEL": "FY2027",
    "PERIOD_START_DATE": "2026-08-01",
    "PERIOD_END_DATE": "2027-07-31",
    "MONTHLY_EXPENSE_BASE_CENTS": 200000,
    "RESERVE_BALANCE_CENTS": 500000,
    "AREA_CODE": "HOUSING",
    "AREA_NAME": "Housing",
    "EDITORIAL_LEAD_USER_ID": "user-ed-lead-1",
    "TIER_CODE": "SUSTAINER",
    "TIER_NAME": "Sustainer",
    "TIER_CONTRIBUTION_AMOUNT_CENTS": 2500,
    "FUNDER_LEGAL_NAME": "Larkspur Foundation",
    "DISCLOSURE_TEXT": (
        "This funder supports our reporting on this beat and exercises no "
        "influence over editorial judgment, assignment or publication."
    ),
    "PROPOSAL_TITLE": "Housing Accountability Reporting",
    "REQUESTED_AMOUNT_CENTS": 350000,
    "RESTRICTION_START_DATE": "2026-09-01",
    "RESTRICTION_END_DATE": "2027-02-28",
    "COLLABORATION_TITLE": "Housing Investigation",
    "WINDOW_START": "2026-09-01T00:00:00Z",
    "WINDOW_END": "2026-10-01T00:00:00Z",
    "TOTAL_COST_CENTS": 100000,
}
