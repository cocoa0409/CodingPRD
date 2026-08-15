"""Domain thresholds and numeric constants from the PRD."""

THRESHOLDS = {
    # Entry-fee discounts (PRD §3.2)
    "MEMBER_DISCOUNT_PCT": 0.10,
    "MULTI_VEHICLE_DISCOUNT_PCT": 0.25,
    # Withdrawal refund tiers in hours (PRD §3.4)
    "REFUND_FULL_HOURS": 168,
    "REFUND_HALF_HOURS": 48,
    # Weather posture refund variants (PRD §3.7)
    "POSTPONE_CREDIT_PCT": 0.25,
    # Noise ordinance (PRD §3.8)
    "DAY_LIMIT_DB": 95.0,
    "CURFEW_LIMIT_DB": 85.0,
    "EXCEEDANCE_SUSPENSION_THRESHOLD": 3,
    # Booth fees (PRD §3.9)
    "TIER_FEE_SINGLE": 7500,
    "TIER_FEE_DOUBLE": 14000,
    "TIER_FEE_SPONSOR": 25000,
    "POWER_FEE_CENTS": 1500,
    # People's choice ballot weights (PRD §3.6)
    "MEMBER_BALLOT_WEIGHT": 2,
    "NON_MEMBER_BALLOT_WEIGHT": 1,
}

# Sheet criterion weights (PRD §3.5)
CRITERION_WEIGHTS = {
    "EXTERIOR": 1.0,
    "INTERIOR": 0.75,
    "ENGINE": 1.5,
    "AUTHENTICITY": 2.0,
    "CONDITION": 1.25,
}

TEST_DEFAULTS = {
    # The logical clock starts at this instant on server boot (PRD §2.7).
    "CLOCK_START": "2026-08-01T00:00:00Z",
    "EVENT_DATE": "2026-08-15",
    "GATES_OPEN_AT": "2026-08-15T09:00:00Z",
    "JUDGING_START_AT": "2026-08-15T12:00:00Z",
    "JUDGING_END_AT": "2026-08-15T14:00:00Z",
    "BALLOT_CLOSE_AT": "2026-08-15T14:30:00Z",
    "PREREG_DEADLINE": "2026-08-14T23:59:59Z",
    "CURFEW_START": "22:00",
    "CURFEW_END": "07:00",
    "PREREG_FEE_CENTS": 3000,
    "DAY_OF_FEE_CENTS": 4500,
}

# A well-formed UUID that never resolves to a persisted resource.
MISSING_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
