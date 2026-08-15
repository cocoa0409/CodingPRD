"""Domain thresholds and defaults stated in PRD §2.4, §3.1, §3.5-§3.9."""

# Logical clock (PRD §2.4): startup instant.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# Payer / contract creation defaults (PRD §3.1).
DEFAULT_APPEAL_DEADLINE_DAYS = 45
DEFAULT_PAYMENT_TERMS_DAYS = 30
DEFAULT_UNDERPAYMENT_THRESHOLD_CENTS = 5000
DEFAULT_UNDERPAYMENT_THRESHOLD_BP = 100

# Basis-point denominator (PRD §2.6).
BP_DENOMINATOR = 10000

# Trailing-volume window for tiers and proposal modeling (PRD §3.5, §3.8).
VOLUME_WINDOW_DAYS = 364

# Appeal response clocks per level (PRD §3.7).
RESPONSE_DAYS = {1: 30, 2: 30, 3: 45, 4: 60}

# Money gates (PRD §3.7).
ARBITRATION_MIN_OUTSTANDING_CENTS = 100000
WRITE_OFF_DIRECTOR_CAP_CENTS = 250000

# Alert windows (PRD §3.9).
TERM_EXPIRING_90_DAYS = 90
TERM_EXPIRING_30_DAYS = 30
ESCALATOR_UPCOMING_DAYS = 30

# Standard contract window used across fixtures (covers June claim stays and
# stays active well past the default clock).
CONTRACT_EFFECTIVE_DATE = "2026-01-01"
CONTRACT_EXPIRATION_DATE = "2026-12-31"

# Standard rate/claim amounts used across fixtures.
DEFAULT_BASE_RATE_CENTS = 100000
DEFAULT_BILLED_CHARGES_CENTS = 500000
