"""Domain thresholds and shared constants from PRD §2.5, §2.7, and §3."""

# PRD §2.5: the logical clock's startup default, before any clock operation.
STARTUP_CLOCK_UTC = "2026-05-01T00:00:00Z"
STARTUP_CLOCK_UTC_MS = "2026-05-01T00:00:00.000Z"

# Standard June-2026 application window used across scenarios.
WINDOW_OPEN = "2026-06-01T00:00:00Z"
WINDOW_CLOSE = "2026-06-30T00:00:00Z"
MID_WINDOW = "2026-06-10T00:00:00Z"

# PRD §3.6: an offer's response_deadline is exactly 10 days after offered_at.
OFFER_RESPONSE_DAYS = 10
# PRD §3.4: a certification's valid_until is exactly 180 days after certified_at.
CERTIFICATION_VALID_DAYS = 180
# PRD §3.6: an entry is removed once its refusal_count reaches 2.
MAX_REFUSALS = 2
# PRD §3.7: notice_response_days defaults to 30.
DEFAULT_NOTICE_RESPONSE_DAYS = 30

# PRD §3.3: household_size between 1 and 12 inclusive.
HOUSEHOLD_SIZE_MIN = 1
HOUSEHOLD_SIZE_MAX = 12

DEFAULT_AMI_LIMIT_CENTS = 4_000_000
DEFAULT_HOUSEHOLD_SIZE = 2
DEFAULT_SELF_REPORTED_INCOME_CENTS = 3_000_000
DEFAULT_CERT_INCOME_SOURCE = {
    "source_type": "SALARY",
    "amount_per_period_cents": 250000,
    "periods_per_year": 12,
}
DEFAULT_MARKETING_CHANNELS = ["LOCAL_NEWSPAPER", "HOUSING_AUTHORITY_WEBSITE"]
DEFAULT_TARGET_AMI_TIER = "AMI_50"

# Opaque operator identities (PRD §2.1: recorded on audit fields, never
# compared to entity ids). Lottery operators and certifying officers use
# distinct ids so the segregation-of-duties rule of PRD §2.9 stays satisfied.
LOTTERY_ADMIN_USER = "lot-1"
COMPLIANCE_OFFICER_USER = "co-1"
