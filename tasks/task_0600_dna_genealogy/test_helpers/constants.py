"""Domain thresholds and constants stated in the PRD."""

# ─── Logical clock (PRD §2.4) ────────────────────────────────────────────────
CLOCK_START = "2026-05-01T00:00:00Z"

# ─── Subscription / billing (PRD §3.1, §3.2) ────────────────────────────────
TIER_FEE_CENTS = {"FREE": 0, "PLUS": 1999, "PRO": 7999}
BILLING_PERIOD_DAYS = 30
GRACE_PERIOD_DAYS = 14
REPORT_UNLOCK_FEE_CENTS = 300

# Tier-upgrade charge pipeline (PRD §3.2)
LOYALTY_DISCOUNT_TIERS = [(5000, 0.10), (2000, 0.05), (0, 0.00)]
PROCESSING_FEE_PCT = 0.029
PROCESSING_FEE_MIN_CENTS = 30

# ─── Family tree (PRD §3.9) ─────────────────────────────────────────────────
TIER_TREE_PERSON_LIMIT = {"FREE": 3, "PLUS": 250, "PRO": 999999}

# ─── Kit / lab pipeline (PRD §3.3, §3.4, §3.5) ──────────────────────────────
KIT_PRICE_CENTS = 9900
MIN_DNA_YIELD_NG = 200.0
MAX_EXTRACTION_ATTEMPTS = 3
MIN_CALL_RATE = 0.98

# ─── Consent (PRD §3.6) ─────────────────────────────────────────────────────
CONSENT_COOLING_OFF_HOURS = 24

# ─── Reports (PRD §3.7) ─────────────────────────────────────────────────────
MINOR_POPULATION_FLOOR_PCT = 1.00
HEALTH_TRAIT_MARKER_CEILING = 12

# ─── Relative matching (PRD §3.8) ───────────────────────────────────────────
CM_PER_MARKER = 4.00
MATCH_MIN_CM = 8.00
MAX_CM_FOR_FULL_CONFIDENCE = 400.00
W_CM = 0.70
W_SEG = 0.30
CHIP_MISMATCH_PENALTY = 0.05
EXPECTED_SEGMENTS = {
    "PARENT_CHILD": 40,
    "SIBLING": 30,
    "CLOSE_COUSIN": 12,
    "DISTANT_COUSIN": 4,
}
RELATIONSHIP_THRESHOLDS_CM = {
    "PARENT_CHILD": 240.00,
    "SIBLING": 120.00,
    "CLOSE_COUSIN": 40.00,
    "DISTANT_COUSIN": 8.00,
}

# ─── Privacy (PRD §3.10) ────────────────────────────────────────────────────
PURGE_GRACE_DAYS = 7
EXPORT_URL_PREFIX = "https://export.dna.example/"

# ─── Test defaults ──────────────────────────────────────────────────────────
TEST_DEFAULTS = {
    "GOOD_YIELD_NG": 500.0,
    "BAD_YIELD_NG": 10.0,
    "GOOD_CALL_RATE": 0.99,
    "BAD_CALL_RATE": 0.97,
    "RUN_START_AT": "2026-05-01T02:00:00Z",
    "RUN_END_AT": "2026-05-01T06:00:00Z",
}

# A syntactically valid UUID that never resolves to a record.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
