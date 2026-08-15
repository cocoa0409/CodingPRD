"""Domain thresholds and rates — numeric constants from PRD §3."""

# Logical clock default at startup (PRD §2.6)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Quote pricing (PRD §3.3)
VEHICLE_CLASS_RATES = {
    "STANDARD": {"mileage_rate_cents": 250, "hourly_rate_cents": 15000,
                 "included_hours": 5, "included_miles": 100},
    "PREMIUM": {"mileage_rate_cents": 350, "hourly_rate_cents": 20000,
                "included_hours": 5, "included_miles": 100},
    "EXECUTIVE": {"mileage_rate_cents": 500, "hourly_rate_cents": 30000,
                  "included_hours": 5, "included_miles": 100},
}
MILEAGE_PRIMARY_RATIO = 55.0
OVERNIGHT_RATE_PER_NIGHT_CENTS = 25000
RELIEF_DRIVER_FLAT_CENTS = 45000
ADA_SURCHARGE_PCT = 0.05
TAX_RATE = 0.0825
QUOTE_EXPIRY_HOURS = 72

# Deposit tiers by lead-time hours (PRD §3.4)
DEPOSIT_TIER_1_HOURS = 720   # >= 720h -> 10%
DEPOSIT_TIER_2_HOURS = 336   # >= 336h -> 25%
DEPOSIT_TIER_3_HOURS = 168   # >= 168h -> 50%
DEPOSIT_TIER_4_HOURS = 48    # >= 48h  -> 75%; below -> 100%

# Cancellation fee tiers by lead-time hours (PRD §3.6)
CANCEL_TIER_1_HOURS = 720    # >= 720h -> 0%
CANCEL_TIER_2_HOURS = 336    # >= 336h -> 10%
CANCEL_TIER_3_HOURS = 168    # >= 168h -> 25%
CANCEL_TIER_4_HOURS = 72     # >= 72h  -> 50%
CANCEL_TIER_5_HOURS = 24     # >= 24h  -> 75%; below -> 100%

# Fuel surcharge tiers by actual miles (PRD §3.5)
FUEL_TIER_1_MILES = 100      # <= 100 -> 0%
FUEL_TIER_2_MILES = 300      # <= 300 -> 3%
FUEL_TIER_3_MILES = 600      # <= 600 -> 5%; above -> 8%

# Extra-hours billing multiplier (PRD §3.5)
EXTRA_HOURS_MULTIPLIER = 1.5

# Hours-of-service limits (PRD §3.2, §3.4)
MAX_DRIVING_HOURS = 11.0
MAX_ON_DUTY_WINDOW_HOURS = 14.0
CYCLE_70_8_LIMIT = 70.0
CYCLE_60_7_LIMIT = 60.0
REST_HOURS_REQUIRED = 10
MANDATORY_BREAK_AFTER_HOURS = 8.0
MANDATORY_BREAK_MINUTES = 30
OVERNIGHT_HOURS_THRESHOLD = 10

# Assignment eligibility (PRD §3.4)
MIN_DRIVER_SAFETY_SCORE_ASSIGN = 50.0
MIN_DRIVER_SAFETY_SCORE_REINSTATE = 30.0

# Maintenance (PRD §3.8)
MAINTENANCE_INTERVAL_MILES = 10000

# Driver safety-score schedule (PRD §3.9)
DRIVER_SCORE_BASE = 100.0
DRIVER_SEVERITY_DEDUCTION = {"MINOR": 2.0, "MODERATE": 5.0, "MAJOR": 12.0,
                             "CRITICAL": 25.0}
ACCIDENT_MULTIPLIER = 1.5
HOS_VIOLATION_MULTIPLIER = 1.2

# Customer safety-audit-score schedule (PRD §3.9)
CUSTOMER_SCORE_BASE = 100.0
CUSTOMER_SEVERITY_DEDUCTION = {"MINOR": 3.0, "MODERATE": 7.0, "MAJOR": 15.0,
                               "CRITICAL": 30.0}
BREAKDOWN_SHORT_DELAY_MINUTES = 60
BREAKDOWN_SHORT_DELAY_DEDUCTION = 5.0
BREAKDOWN_LONG_DELAY_MINUTES = 240
BREAKDOWN_LONG_DELAY_DEDUCTION = 10.0
RECENCY_DECAY_DAYS = 365.0
MIN_RECENCY_WEIGHT = 0.1

# Breakdown compensation tiers by delay minutes (PRD §3.7)
COMP_TIER_1_MIN = 60         # < 60 -> 0%
COMP_TIER_2_MIN = 120        # < 120 -> 5%
COMP_TIER_3_MIN = 240        # < 240 -> 10%
COMP_TIER_4_MIN = 480        # < 480 -> 20%; >= 480 -> 35%

TEST_DEFAULTS = {
    "TRIP_DATE": "2026-09-01T08:00:00Z",
    "RETURN_DATE": "2026-09-01T16:00:00Z",
    "PASSENGER_COUNT": 40,
    "ESTIMATED_MILES": 300,
    "ESTIMATED_HOURS": 5,
    "SEATING_CAPACITY": 56,
    "MAINTENANCE_DUE_MILES": 50000,
    "DOT_INSPECTION_EXPIRY": "2027-01-01T00:00:00Z",
    "INSURANCE_EXPIRY": "2027-01-01T00:00:00Z",
}
