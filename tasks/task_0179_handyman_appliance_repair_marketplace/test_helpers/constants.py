"""Domain thresholds — numeric constants from PRD calculations (§3.6, §3.7)."""

# Part-line truck-stock markup clamp (PRD §3.6).
TRUCK_MARKUP_CAP_CENTS = 5000
TRUCK_MARKUP_FLOOR_CENTS = 300
SPECIAL_ORDER_HANDLING_CENTS = 1500

# Trip-fee geography + waiver (PRD §3.7).
LOCAL_TRIP_FEE_CENTS = 2500
REMOTE_TRIP_FEE_CENTS = 6000
FREE_TRIP_THRESHOLD_CENTS = 40000

# Scheduling buffers (PRD §3.4).
TRAVEL_BUFFER_MINUTES = 60

# Default category warranty window (PRD §3.1).
DEFAULT_CALLBACK_WARRANTY_DAYS = 30

# Default pro truck-stock markup (PRD §3.2).
DEFAULT_TRUCK_STOCK_MARKUP_PCT = 0.25
