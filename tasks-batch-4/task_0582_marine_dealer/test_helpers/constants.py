"""Domain thresholds — numeric constants from the Marine Dealer PRD calculations."""

# PRD §3.3: minimum down payment is 10% (1000 bps) of sale price, ceiling-rounded.
MIN_DOWN_BPS = 1000

# PRD §3.2: floor-plan interest uses a 365-day year; the payoff quote projects the
# lender's 10-day notice period; a curtailment is due only after a 90-day window.
DAYS_PER_YEAR = 365
PAYOFF_NOTICE_DAYS = 10
CURTAILMENT_DUE_DAYS = 90

# PRD §3.5: a repair order's bay window is extended by a 30-minute buffer at each end.
BAY_BUFFER_MINUTES = 30

# Basis-point divisor used by every rate computation (PRD §2.7).
BPS_DIVISOR = 10000

# Server startup default for the logical clock (PRD §2.6).
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"
