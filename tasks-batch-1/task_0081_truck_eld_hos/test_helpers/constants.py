"""Domain thresholds — numeric constants from PRD Hours-of-Service rules (§3.4, §3.5, §3.9)."""

# Standard-variant HOS limits (PRD §3.5).
DRIVING_LIMIT_MIN = 660        # 11 hours
WINDOW_LIMIT_MIN = 840         # 14 hours
BREAK_REQUIRED_AFTER_MIN = 480  # 8 hours of driving without a 30-min break
BREAK_MIN_MINUTES = 30
RESET_OFF_DUTY_MIN = 600       # 10 hours qualifying off-duty break

# Cycle limits (PRD §3.4, §3.5).
CYCLE_70_LIMIT_MIN = 4200      # 70 hours
CYCLE_60_LIMIT_MIN = 3600      # 60 hours
CYCLE_70_WINDOW_DAYS = 8
CYCLE_60_WINDOW_DAYS = 7

# Adverse-conditions extended limits (PRD §3.9).
DRIVING_LIMIT_ADVERSE_MIN = 780   # 13 hours
WINDOW_LIMIT_ADVERSE_MIN = 960    # 16 hours

# Sleeper-berth split (PRD §3.4).
LONG_REST_MIN = 420     # 7 hours, entirely SLEEPER_BERTH
SHORT_REST_MIN = 120    # 2 hours, SLEEPER_BERTH or OFF_DUTY
PAIR_TOTAL_MIN = 600    # 10 hours

# Violation overage floor (PRD §3.5).
OVERAGE_FLOOR = 1

# Pagination bounds (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# System-generated auto-dismiss notes (PRD §3.6, §3.9).
NOTE_AUTO_DISMISSED_CORRECTED = "auto-dismissed: corrected"
NOTE_AUTO_DISMISSED_ADVERSE = "auto-dismissed: adverse conditions"
