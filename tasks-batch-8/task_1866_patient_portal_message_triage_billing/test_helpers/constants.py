"""Domain thresholds and shared constants from the PRD.

- E-visit tier schedule and minimum minutes: PRD §3.6.
- Inbox overload threshold (five or more): PRD §2.11.
- Logical clock startup default: PRD §2.5.
"""

# Logical clock (PRD §2.5): startup default before any clock-set call.
LOGICAL_CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# E-visit billing (PRD §3.6).
EVISIT_MIN_MINUTES = 5
FEE_99421_CENTS = 5000
FEE_99422_CENTS = 8000
FEE_99423_CENTS = 12000

# Inbox load accounting (PRD §2.11): overloaded iff open_inbox_count >= 5.
OVERLOAD_THRESHOLD = 5

# Standard provider-pool response targets used across tests (minutes).
PROVIDER_TARGET_EMERGENT = 30
PROVIDER_TARGET_URGENT = 120
PROVIDER_TARGET_ROUTINE = 1440

# Standard nurse-pool response targets used across tests (minutes).
NURSE_TARGET_EMERGENT = 15
NURSE_TARGET_URGENT = 60
NURSE_TARGET_ROUTINE = 240

# A fixed logical-clock instant most workflows pin before intake.
WORKFLOW_CLOCK = "2026-08-03T10:00:00Z"

# A wide coverage span containing every logical-clock instant the tests use.
WIDE_COVERAGE_START = "2026-08-03T00:00:00Z"
WIDE_COVERAGE_END = "2026-08-31T23:59:00Z"

# Patient defaults.
DEFAULT_COPAY_CENTS = 2500
DEFAULT_COINSURANCE_PCT = 0.25

# A well-formed UUID that no server will ever mint for a real resource.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"
