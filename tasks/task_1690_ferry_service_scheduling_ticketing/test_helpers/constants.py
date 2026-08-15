"""Domain thresholds — numeric constants named in the PRD's calculation rules.

Sources: deck-split ratios and floors (PRD §3.4), vehicle length bands and
caps (PRD §3.5/§3.6), fuel surcharge tiers (PRD §3.2), passenger escalator
(PRD §2.8), crew rest gap (PRD §3.3), peak vehicle multiplier (PRD §3.5),
logical clock default (PRD §2.4).
"""

# Deck allocation (PRD §3.4)
PEAK_RESERVED_RATIO = 0.70
OFF_PEAK_RESERVED_RATIO = 0.60
STANDBY_FLOOR_FEET = 40
RESERVED_FLOOR_FEET = 20

# Fare quote (PRD §3.5)
PEAK_VEHICLE_MULTIPLIER = 1.25
OVERSIZE_LENGTH_THRESHOLD_FEET = 22
BOOKING_MAX_VEHICLE_FEET = 80

# Standby lane (PRD §3.6)
STANDBY_MAX_VEHICLE_FEET = 60

# Manning (PRD §2.8)
PASSENGER_ESCALATOR_THRESHOLD = 500
MANNING_TABLE = {
    "SMALL": {"CAPTAIN": 1, "DECK": 1, "ENGINE": 0},
    "MEDIUM": {"CAPTAIN": 1, "DECK": 2, "ENGINE": 1},
    "LARGE": {"CAPTAIN": 1, "DECK": 3, "ENGINE": 2},
}

# Crew rest rule (PRD §3.3)
CREW_REST_MINUTES = 480

# Fuel surcharge tiers (PRD §3.2)
FUEL_TIER1_LOW_CENTS = 300
FUEL_TIER2_LOW_CENTS = 500
FUEL_TIER1_SURCHARGE_CENTS = 100
FUEL_TIER2_SURCHARGE_CENTS = 250

# Logical clock fixed server default (PRD §2.4)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Default component rates used by fixtures (integer cents)
DEFAULT_RATES = {
    "passenger_standard_cents": 1000,
    "passenger_resident_cents": 800,
    "passenger_commuter_cents": 600,
    "vehicle_standard_base_cents": 2000,
    "vehicle_oversize_base_cents": 4000,
    "vehicle_overlength_per_foot_cents": 100,
}
