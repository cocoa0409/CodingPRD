"""Domain thresholds — numeric constants drawn from the PRD calculations."""

# Session charge (PRD §3.11)
MINUTES_PER_HOUR = 60

# Material billing (PRD §3.11)
BPS_DENOMINATOR = 10000

# Membership proration (PRD §3.11)
CYCLE_DAYS = 30

# Certification readiness (PRD §3.4 / §3.11)
W_CERT = 0.5
W_ORIENTATION = 0.2
W_SUPERVISED = 0.3
READINESS_GATE = 0.8

# Locker overage (PRD §3.7)
OVERAGE_RATE_CENTS_PER_LITER = 30

# Day-pass rolling window (PRD §3.3)
MAX_DAYPASSES_PER_WINDOW = 3

# Logical clock startup default (PRD §2.4)
CLOCK_DEFAULT = "2026-04-01T00:00:00Z"

# A syntactically-valid UUID that resolves to no resource.
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
