"""Domain thresholds — numeric constants from the PRD pricing and warranty rules.

All monetary values are integer cents (PRD §2.8).
"""

# Pricing constants (PRD §3.3, §3.6).
AFTER_HOURS_MULT = 1.5             # labor multiplier when job.after_hours is true
MAX_DISCOUNT_CENTS = 15000         # cap on the membership labor discount
TRIP_FEE_BASE_CENTS = 8900         # base trip fee when not waived
TRIP_WAIVE_THRESHOLD_CENTS = 50000  # labor-after-discount at/above this waives the trip fee
EMERGENCY_SURCHARGE_CENTS = 12000  # added when job.priority == EMERGENCY

# After-hours cutoff (PRD §3.2): window_start at hour 18 UTC or later is after-hours.
AFTER_HOURS_CUTOFF_HOUR = 18

# Dispatch routing (PRD §3.2): travel buffer applied to each side of the window.
TRAVEL_BUFFER_MINUTES = 30

# Callback rate (PRD §3.9).
ROLLING_WINDOW = 5

# Warranty (PRD §3.8): callbacks within this many whole days are within_warranty.
WARRANTY_DAYS = 90

# Default credit limit when not supplied on customer creation (PRD §3.1).
DEFAULT_CREDIT_LIMIT_CENTS = 100000

THRESHOLDS = {
    "AFTER_HOURS_MULT": AFTER_HOURS_MULT,
    "MAX_DISCOUNT_CENTS": MAX_DISCOUNT_CENTS,
    "TRIP_FEE_BASE_CENTS": TRIP_FEE_BASE_CENTS,
    "TRIP_WAIVE_THRESHOLD_CENTS": TRIP_WAIVE_THRESHOLD_CENTS,
    "EMERGENCY_SURCHARGE_CENTS": EMERGENCY_SURCHARGE_CENTS,
    "AFTER_HOURS_CUTOFF_HOUR": AFTER_HOURS_CUTOFF_HOUR,
    "TRAVEL_BUFFER_MINUTES": TRAVEL_BUFFER_MINUTES,
    "ROLLING_WINDOW": ROLLING_WINDOW,
    "WARRANTY_DAYS": WARRANTY_DAYS,
    "DEFAULT_CREDIT_LIMIT_CENTS": DEFAULT_CREDIT_LIMIT_CENTS,
}
