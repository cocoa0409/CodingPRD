"""Domain thresholds — numeric constants from PRD calculations and defaults."""

# PRD §3.1 / §2.9 — online reservation hold window.
RESERVATION_HOLD_MINUTES = 30

# PRD §3.4 — majority age for the minor flag.
MAJORITY_AGE = 18

# PRD §3.8 — room-slot cleaning buffer (each side, closed interval).
CLEAN_BUFFER_MINUTES = 15

# PRD §3.5 — follow-up grace period before a DUE record flips to OVERDUE.
GRACE_DAYS = 3

# PRD §2.9 — clinic posture/threshold defaults.
DEFAULT_SURGE_THRESHOLD = 8
DEFAULT_DIVERSION_THRESHOLD = 14

# PRD §2.8 — default self-pay prompt-pay discount.
DEFAULT_SELF_PAY_DISCOUNT_PCT = 0.30

# PRD §3.2 — default mean provider minutes per ESI level (1..5).
DEFAULT_ESI_MINUTES = {1: 40, 2: 30, 3: 20, 4: 12, 5: 8}

# PRD §3.9 — default provider concurrency cap.
DEFAULT_MAX_CONCURRENT_VISITS = 2
