"""Domain thresholds — numeric constants from PRD calculations and rules."""

# Late-cancel window: a cancel >= 12 hours before start is timely (refund),
# strictly inside 12 hours is late (forfeit). Boundary inclusive on timely side. (PRD §3.5)
LATE_CANCEL_WINDOW_HOURS = 12

# Reservation cut-off: reservations close 60 minutes before start;
# now == starts_at - 60min is still OPEN. (PRD §3.4)
RESERVATION_CUTOFF_MINUTES = 60

# No-show suspension threshold: no_show_strikes >= 3 suspends reservations. (PRD §3.1)
NO_SHOW_SUSPEND_THRESHOLD = 3

# Coach turnaround buffer: busy interval extends starts_at + duration + 15min. (PRD §3.4)
COACH_TURNAROUND_MINUTES = 15

# Server logical clock default at startup. (PRD §2.7)
DEFAULT_CLOCK_UTC = "2026-01-01T00:00:00Z"
