"""Domain thresholds — numeric constants from the Mobile Phlebotomy PRD billing/strike rules."""

# Self-pay billing convenience fee constants (PRD §3.10).
SELF_PAY_BASE_CONVENIENCE_CENTS = 3500
SELF_PAY_PER_TUBE_CENTS = 500
SELF_PAY_REDRAW_WAIVER_UNIT_CENTS = 1000

# Insurance billing constants (PRD §3.10).
INSURANCE_FLAT_CONVENIENCE_CENTS = 2500
INSURANCE_REDRAW_WAIVER_UNIT_CENTS = 2500

# Phlebotomist strike suspension threshold (PRD §3.9).
SUSPENSION_THRESHOLD = 3

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Logical clock startup instant (PRD §2.4).
CLOCK_START_UTC = "2026-01-01T00:00:00Z"
