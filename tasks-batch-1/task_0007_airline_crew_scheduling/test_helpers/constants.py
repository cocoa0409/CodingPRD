"""Domain thresholds — numeric constants from PRD §2.7, §2.8, §3.1, §3.4."""

# PRD §2.7: FAA rolling 7-day caps (strict greater-than comparison).
FAA_DUTY_CAP_7D_MIN = 3600       # 60 hours of duty
FAA_FLIGHT_CAP_7D_MIN = 1800     # 30 hours of flight
WINDOW_HOURS = 168               # trailing seven days

# PRD §2.8: Minimum off-duty interval (inclusive comparison).
MIN_REST_MINUTES = 600           # 10 hours

# PRD §3.1: Pairing duty-window buffers.
REPORT_BUFFER_MIN = 60
DEBRIEF_BUFFER_MIN = 30

# PRD §3.4: Reserve-callup exhaustion.
MAX_CALLUP_ATTEMPTS = 5
