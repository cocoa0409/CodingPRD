"""Numeric constants and shared literals taken from the PRD's calculations."""

# The logical clock's fixed startup default.
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Opaque operator identifiers. Two distinct administrators and two distinct
# licensees are needed because the PRD segregates duties by recorded user id.
RIGHTS_ADMIN_ONE = "ra-001"
RIGHTS_ADMIN_TWO = "ra-002"
LICENSEE_ONE = "lic-001"
LICENSEE_TWO = "lic-002"
COMPLIANCE_OFFICER_ONE = "co-001"
COMPLIANCE_OFFICER_TWO = "co-002"

THRESHOLDS = {
    # Initial creation compensation
    "BREADTH_STEP": 0.15,
    "SHORT_TERM_MONTHS": 12,
    "MID_TERM_MONTHS": 36,
    "DURATION_FACTOR_SHORT": 1.00,
    "DURATION_FACTOR_MID": 1.25,
    "DURATION_FACTOR_LONG": 1.60,
    "EXCLUSIVE_FACTOR": 1.35,
    "NON_EXCLUSIVE_FACTOR": 1.00,
    # Per-use royalty
    "REACH_TIER_1": 1_000_000,
    "REACH_TIER_2": 10_000_000,
    "REACH_FACTOR_1": 1.00,
    "REACH_FACTOR_2": 1.40,
    "REACH_FACTOR_3": 1.90,
    "TERRITORY_STEP": 0.10,
    # Terms, windows and caps
    "MIN_CONSENT_TERM_DAYS": 30,
    "MAX_REVISION_ROUNDS": 3,
    "REVIEW_WINDOW_DAYS": 7,
    "PURGE_EXECUTION_GRACE_DAYS": 7,
    "MAX_OVERLAPPING_LICENSES": 2,
    "UNION_FLOOR_RATIO": 0.5,
    # Licensee billing
    "SURCHARGE_RATE_ADVERTISING": 0.0175,
    "SURCHARGE_RATE_ENTERTAINMENT": 0.0125,
    # Infringement severity
    "WEIGHT_CONFIDENCE": 0.60,
    "WEIGHT_REACH": 0.25,
    "WEIGHT_POSTURE": 0.15,
    "REACH_SATURATION": 10_000_000,
    "MANDATORY_TAKEDOWN_THRESHOLD": 0.7500,
    "ESCALATION_FLOOR": 0.5000,
}

MEDIA_FLOOR_RANK = {
    "ADVERTISING": 5,
    "FEATURE_FILM": 4,
    "EPISODIC": 3,
    "VIDEO_GAME": 2,
    "SOCIAL": 1,
}

MEDIA_MULTIPLIER = {
    "ADVERTISING": 1.50,
    "FEATURE_FILM": 1.30,
    "EPISODIC": 1.15,
    "VIDEO_GAME": 1.10,
    "SOCIAL": 1.00,
}

DISCLOSURE_PLACEMENT_RANK = {
    "METADATA_ONLY": 1,
    "END_CARD": 2,
    "PRE_ROLL": 3,
    "PERSISTENT_BUG": 4,
}

POSTURE_FACTOR = {
    "FROZEN": 1.0,
    "RESTRICTED": 0.6,
    "CLEAR": 0.3,
}

TEST_DEFAULTS = {
    "DOMICILE_STATE": "CA",
    "TALENT_NAME": "Ava Reyes",
    "INITIAL_CREATION_FEE_CENTS": 300_000,
    "PER_USE_BASE_FEE_CENTS": 150_000,
    "TALENT_SHARE_PCT": 0.75,
    "AGENCY_SHARE_PCT": 0.20,
    "ADMINISTRATOR_SHARE_PCT": 0.05,
    "EFFECTIVE_FROM": "2026-08-01T00:00:00Z",
    "EFFECTIVE_UNTIL": "2027-08-01T00:00:00Z",
    "LICENSEE_NAME": "Northlight Ads",
}
