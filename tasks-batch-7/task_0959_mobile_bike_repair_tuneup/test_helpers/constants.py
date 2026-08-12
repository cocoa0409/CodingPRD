"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# PRD §3.9: 8% tax, surcharge brackets keyed on pre-surcharge subtotal.
TAX_RATE = 0.08
SURCHARGE_T1_MIN = 10000
SURCHARGE_T1_CENTS = 500
SURCHARGE_T2_MIN = 20000
SURCHARGE_T2_CENTS = 1200

# PRD §3.6: default travel buffer applied around a stop for overlap checks.
DEFAULT_TRAVEL_BUFFER_MINUTES = 15

# PRD §3.4: e-bike battery safety gate.
BATTERY_HEALTH_MIN_PCT = 70

# PRD §3.4: arrival-window shape bounds.
WINDOW_MIN_MINUTES = 30
WINDOW_MAX_MINUTES = 240

# PRD §2.6: logical clock startup value.
CLOCK_START_ISO = "2026-05-01T00:00:00Z"

# Common reusable window (well-formed: 2 hours, after the startup clock).
DEFAULT_WINDOW_START = "2026-05-02T10:00:00Z"
DEFAULT_WINDOW_END = "2026-05-02T12:00:00Z"
DEFAULT_ROUTE_DATE = "2026-05-02"

# Subscription coverage period spanning May 2026 (inclusive both ends).
DEFAULT_PERIOD_START = "2026-05-01T00:00:00Z"
DEFAULT_PERIOD_END = "2026-05-31T23:59:59Z"
