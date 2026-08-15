"""Domain thresholds — numeric constants from PRD §2.6–§2.11."""

THRESHOLDS = {
    # PRD §2.6: STABLE/WATCH posture threshold on sterilized_pct.
    "STABLE_THRESHOLD": 0.75,
    # PRD §2.7: kitten season months (March through July).
    "KITTEN_SEASON_MONTHS": (3, 4, 5, 6, 7),
    # PRD §3.1: is_kitten boundary in whole months.
    "KITTEN_AGE_MONTHS": 6,
    # PRD §2.8: monthly issuance cap per caretaker in cents.
    "MONTHLY_CAP_CENTS": 30000,
    # PRD §2.8: donation-fund reimbursement share of the payable base.
    "DONATION_COVERAGE_PCT": 0.80,
    # PRD §3.8: voucher age in calendar months at which expiry applies.
    "VOUCHER_TTL_MONTHS": 3,
    # PRD §2.11: inclusive decline/growth thresholds on the population ratio.
    "DECLINE_THRESHOLD": 0.20,
    "GROWTH_THRESHOLD": 0.20,
}

TEST_DEFAULTS = {
    "VOUCHER_REIMBURSEMENT_CENTS": 10000,
    "FACE_VALUE_CENTS": 5000,
    "BASE_CAPACITY": 2,
}
