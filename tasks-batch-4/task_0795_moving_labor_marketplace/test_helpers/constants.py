"""Domain thresholds — numeric constants drawn from the PRD's calculation rules (§2.5, §3)."""

# Add-on tax and platform fees (PRD §3.3)
ADDON_TAX_PCT = 0.085          # 8.5% add-on tax, applied per line then summed
SERVICE_FEE_PCT = 0.15         # 15% platform service fee on the surged subtotal
CREW_SURCHARGE_THRESHOLD = 3   # crew surcharge applies when crew_size >= 3

# Payout bonus (PRD §3.7)
ON_TIME_BONUS_PCT = 0.05       # 5% on-time bonus when actual_hours <= estimated_hours

# Reputation discipline (PRD §3.9)
RATING_SUSPEND_THRESHOLD = 2.0  # helper auto-suspended when rating_avg < 2.0

# Cancellation pricing (PRD §3.4)
CANCELLATION_FREE_WINDOW_HOURS = 24  # >= 24h notice => free
CANCEL_FEE_PCT = 0.20                # otherwise 20% of estimated_total_cents

# Availability (PRD §3.5)
TRAVEL_BUFFER_MINUTES = 60      # helper overlap adds a 60-minute travel buffer

# Pagination defaults (PRD §2.3)
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# The logical clock's startup default (PRD §2.9)
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"
