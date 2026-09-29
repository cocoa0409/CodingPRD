"""Domain thresholds and pinned literals taken from the PRD."""

# PRD section 2.5: before the clock has ever been set, it reads exactly this instant.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # PRD section 2.6 — posture branches.
    "MISSING_HIGH_RISK_LOCKDOWN_MIN": 1,
    "OPEN_DISCREPANCY_LOCKDOWN_MIN": 5,
    "RISK_SUM_LOCKDOWN_MIN": 25.00,
    "OPEN_DISCREPANCY_RESTRICTED_MIN": 1,
    "SEALED_LOCATION_RESTRICTED_MIN": 1,
    # PRD section 3.2 — the high-value threshold for GENERAL items, inclusive.
    "HIGH_VALUE_VAULT_MIN_CENTS": 500000,
    # PRD section 3.3 — refrigerated bins must read at most 4.0 degrees Celsius.
    "REFRIGERATION_MAX_C": 4.0,
    # PRD section 3.4 — the ninety-day floor on the FINAL retention variant.
    "FINAL_RETENTION_FLOOR_DAYS": 90,
    # PRD section 3.5 — transfer window maxima by purpose.
    "LAB_ANALYSIS_MAX_DAYS": 30,
    "COURT_PRESENTATION_MAX_DAYS": 3,
    "INVESTIGATIVE_REVIEW_MAX_DAYS": 7,
    # PRD section 3.5 — escort capacity: no custodian may hold more than two
    # overlapping escorts, so the request is refused when the count reaches 2.
    "ESCORT_CAPACITY_LIMIT": 2,
    # PRD section 3.6 — owner notice windows in whole days.
    "FOUND_PROPERTY_NOTICE_DAYS": 90,
    "SEIZED_PROPERTY_NOTICE_DAYS": 30,
    "PUBLICATION_EXTENSION_DAYS": 15,
    # PRD section 3.7 — automatic authorization ceiling (strictly below).
    "AUTO_AUTH_MAX_VALUE_CENTS": 500000,
    # PRD section 3.7 — flat estimate commission on the appraisal.
    "ESTIMATE_COMMISSION_RATE": 0.10,
    # PRD section 3.7 — settled commission tier ladder, inclusive upper bounds.
    "COMMISSION_TIER_1_MAX_CENTS": 50000,
    "COMMISSION_TIER_1_RATE": 0.15,
    "COMMISSION_TIER_2_MAX_CENTS": 500000,
    "COMMISSION_TIER_2_RATE": 0.10,
    "COMMISSION_TIER_3_RATE": 0.07,
    # PRD section 3.7 — storage recovery cap as a share of the post-commission subtotal.
    "STORAGE_RECOVERY_CAP_RATE": 0.30,
    # PRD section 3.7 — auction settlement window.
    "SETTLEMENT_WINDOW_DAYS": 30,
    # PRD section 3.8 — audit buffer of 48 hours on both sides, inclusive.
    "AUDIT_BUFFER_HOURS": 48,
    # PRD section 3.8 — risk factors.
    "RISK_WEIGHT_MISSING": 5.0,
    "RISK_WEIGHT_MISPLACED": 2.0,
    "RISK_VALUE_DIVISOR_CENTS": 1000000,
    "RISK_VALUE_CEILING": 2.0,
    "RISK_CATEGORY_MULTIPLIER_SENSITIVE": 1.5,
    "RISK_CATEGORY_MULTIPLIER_PLAIN": 1.0,
}

# PRD section 3.7 — daily storage recovery rate in cents by required storage category.
STORAGE_DAILY_RATE_CENTS = {
    "GENERAL": 25,
    "REFRIGERATED": 120,
    "HIGH_VALUE_VAULT": 60,
    "OVERSIZED_YARD": 200,
}

# PRD section 3.2 — permitted packaging per item category.
PERMITTED_PACKAGING = {
    "BIOLOGICAL": ["SHARPS_TUBE", "RIGID_BOX"],
    "CURRENCY": ["SEALED_ENVELOPE"],
    "FIREARM": ["RIGID_BOX", "CHAIN_TAG_ONLY"],
    "NARCOTICS": ["SEALED_ENVELOPE", "RIGID_BOX"],
    "OVERSIZED": ["PALLET_WRAP", "CHAIN_TAG_ONLY"],
    "GENERAL": [
        "SEALED_ENVELOPE",
        "PAPER_BAG",
        "RIGID_BOX",
        "PALLET_WRAP",
        "CHAIN_TAG_ONLY",
    ],
}

# PRD section 3.2 — required storage category derivation for non-GENERAL categories.
REQUIRED_STORAGE_CATEGORY = {
    "BIOLOGICAL": "REFRIGERATED",
    "CURRENCY": "HIGH_VALUE_VAULT",
    "FIREARM": "HIGH_VALUE_VAULT",
    "NARCOTICS": "HIGH_VALUE_VAULT",
    "OVERSIZED": "OVERSIZED_YARD",
}

# PRD section 2.6 — the categories that make a MISSING discrepancy high risk.
HIGH_RISK_CATEGORIES = ["FIREARM", "CURRENCY", "NARCOTICS"]

# PRD section 2.6 — the literal denial reason written when a room locks down.
DENIAL_REASON_ROOM_LOCKED_DOWN = "ROOM_LOCKED_DOWN"

# PRD section 2.3 — pagination defaults and bounds.
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

TEST_DEFAULTS = {
    "AGENCY_CODE": "CPD",
    "ROOM_NAME": "Central Property Unit",
    "CERTIFICATION_EXPIRES_AT": "2028-01-01T00:00:00Z",
    "SEIZED_AT": "2026-07-31T12:00:00Z",
}
