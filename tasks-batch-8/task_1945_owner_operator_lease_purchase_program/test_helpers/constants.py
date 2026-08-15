"""Domain thresholds — numeric constants from the PRD's calculation rules.

PRD references: per-mile maintenance reserve 12.5 cents (section 3.4),
lane commitment floor 50000 cents (section 3.5), bay turnover buffer 2 hours
(section 3.6), default eligibility at 3 missed payments (section 3.7),
early-buyout fee rate one-tenth and quote TTL 7 days (section 3.8).
"""

THRESHOLDS = {
    "MAINT_CPM_CENTS": 12.5,
    "LANE_COMMITMENT_MIN_CENTS": 50000,
    "BAY_BUFFER_HOURS": 2,
    "DEFAULT_THRESHOLD": 3,
    "EARLY_FEE_RATE": 0.10,
    "QUOTE_TTL_DAYS": 7,
}

# Standard lease terms shared by most scenarios: start 2026-08-03, 52 weeks
# (term end 2027-08-02); weekly payment 65000; escrow 20000/week; guarantee 150000.
TEST_DEFAULTS = {
    "START_DATE": "2026-08-03",
    "TERM_WEEKS": 52,
    "TERM_END": "2027-08-02",
    "WEEKLY_PAYMENT_CENTS": 65000,
    "ESCROW_WEEKLY_CONTRIBUTION_CENTS": 20000,
    "ESCROW_CAP_CENTS": 500000,
    "BUYOUT_BASE_PRICE_CENTS": 4500000,
    "MIN_REVENUE_GUARANTEE_WEEKLY_CENTS": 150000,
    "DOC_EXPIRES_ON": "2027-08-01",
}

# Week-start Mondays within the standard term and the instant each week closes
# (week_start + 7 days).
WEEKS = {
    "W1": "2026-08-03",
    "W2": "2026-08-10",
    "W3": "2026-08-17",
    "W4": "2026-08-24",
}

WEEK_CLOSED_CLOCK = {
    "W1": "2026-08-12T00:00:00Z",
    "W2": "2026-08-19T00:00:00Z",
    "W3": "2026-08-26T00:00:00Z",
    "W4": "2026-09-02T00:00:00Z",
}

REQUIRED_DOC_TYPES = ("W9", "OPERATING_AUTHORITY", "INSURANCE_CERTIFICATE")
