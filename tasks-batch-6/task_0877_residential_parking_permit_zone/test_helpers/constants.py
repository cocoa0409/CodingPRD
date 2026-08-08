"""Domain thresholds and numeric constants from the PRD calculations (§2, §3)."""

# Global program constants (PRD §2.6, §3.5, §3.6, §3.8).
THRESHOLDS = {
    "PROOF_VALIDITY_DAYS": 365,       # a VERIFIED proof is valid this many days
    "RENEWAL_WINDOW_DAYS": 60,        # renewal window before expires_at
    "REVOKE_UPHELD_THRESHOLD": 3,     # this many UPHELD citations auto-revoke a permit
    "REFUND_ADMIN_FEE_CENTS": 2000,   # withheld on VOLUNTARY refunds only
    "REPEAT_THRESHOLD": 2,            # prior UPHELD at/above this -> REPEAT_OFFENDER
    "ESCALATION_MULTIPLIER": 2,
    "MIN_FINE_CENTS": 2500,
    "MAX_FINE_CENTS": 25000,
    "MONTHS_PER_YEAR": 12,
}

# Base fines per violation type (PRD §3.8).
BASE_FINE_CENTS = {
    "NO_PERMIT": 7500,
    "EXPIRED_PERMIT": 5000,
    "ZONE_VIOLATION": 5000,
}

# The server logical clock startup default (PRD §2.6).
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

# Common test values.
TEST_DEFAULTS = {
    "PERMIT_ANNUAL_FEE_CENTS": 12000,
    "VISITOR_PASS_FEE_CENTS": 500,
}
