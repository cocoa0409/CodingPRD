"""Domain thresholds — numeric constants from PRD calculations (§2.5, §2.6, §3)."""

THRESHOLDS = {
    # Application composite (PRD §3.1)
    "APPROVAL_THRESHOLD": 75.0,
    "RUBRIC_WEIGHT": 0.6,
    "INTERVIEW_WEIGHT": 0.4,
    # Monitoring compliance index (PRD §3.3)
    "FAILING_BAND": 60,
    "WEIGHT_ACADEMIC": 0.5,
    "WEIGHT_FINANCIAL": 0.25,
    "WEIGHT_OPERATIONAL": 0.25,
    # Standing bands (PRD §3.3)
    "GOOD_FLOOR": 80.0,
    "NOTICE_FLOOR": 65.0,
    "PROBATION_FLOOR": 50.0,
    # Renewal term tiers (PRD §3.6)
    "TIER_10_AVG": 90.0,
    "TIER_5_AVG": 75.0,
    "TIER_3_AVG": 60.0,
    # Lottery assignment (PRD §3.4)
    "PREFERENCE_WEIGHT": 10,
    # Supplemental funding bands in cents (PRD §3.8)
    "SMALL_CAP_CENTS": 200_000_000,
    "MID_CAP_CENTS": 600_000_000,
    "SUPP_SMALL": 0.12,
    "SUPP_MID": 0.08,
    "SUPP_LARGE": 0.05,
    # Fee rate tiers by enrollment (PRD §3.8)
    "TIER1_MAX_ADM": 300,
    "TIER2_MAX_ADM": 800,
    "RATE_TIER1": 0.025,
    "RATE_TIER2": 0.020,
    "RATE_TIER3": 0.015,
}

CLOCK = {
    # PRD §2.5: startup default of the logical clock
    "DEFAULT": "2026-05-01T00:00:00Z",
    # Inside the renewal window of the standard contract term (PRD §3.6)
    "RENEWAL_OPEN": "2032-01-15T00:00:00Z",
    # Exactly thirty days after RENEWAL_OPEN (appeal window edge)
    "RENEWAL_DECIDED_PLUS_30D": "2032-02-14T00:00:00Z",
    "RENEWAL_DECIDED_PLUS_30D_1S": "2032-02-14T00:00:01Z",
    # Past the window used by renewal-finalize denial flows
    "AFTER_APPEAL_WINDOW": "2032-02-15T00:00:00Z",
    # Thirty days after the default clock (inclusive appeal-window edge)
    "DEFAULT_PLUS_30D": "2026-05-31T00:00:00Z",
    "DEFAULT_PLUS_30D_1S": "2026-05-31T00:00:01Z",
    # One day past a corrective due date computed at the default clock
    "PLAN_OVERDUE": "2026-06-01T00:00:00Z",
}

CONTRACT = {
    "FRAMEWORK_VERSION": "FW-1",
    "TERM_START": "2027-07-01T00:00:00Z",
    "TERM_END": "2032-06-30T00:00:00Z",
    # Successor term used for renewal/overlap scenarios
    "NEXT_TERM_START": "2032-07-01T00:00:00Z",
    "NEXT_TERM_END": "2037-06-30T00:00:00Z",
}

TEST_DEFAULTS = {
    "BASE_PER_PUPIL_CENTS": 800000,
    "ESTIMATED_ENROLLMENT": 400,
    "AUDITED_ENROLLMENT": 500,
    "QUALIFYING_SUPPLEMENTAL_PUPILS": 100,
}
