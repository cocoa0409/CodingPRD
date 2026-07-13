"""Domain thresholds — numeric constants from the PRD fee and points formulas."""

# Service base charges by ordered/actual service level (integer cents) — PRD §3.2 / §3.6.
SERVICE_BASE_CENTS = {
    "THRESHOLD": 4000,
    "ROOM_OF_CHOICE": 7000,
    "WHITE_GLOVE": 12000,
}

# Weight surcharge tiers (integer cents) — PRD §3.2 / §3.6.
#   weight_lbs <= 75      -> 0
#   76 .. 150             -> 1500
#   151 .. 300            -> 3500
#   > 300                 -> 6000
WEIGHT_TIERS = [
    (75, 0),
    (150, 1500),
    (300, 3500),
]
WEIGHT_TIER_TOP_CENTS = 6000

PER_FLIGHT_CENTS = 800
MAX_BILLABLE_FLIGHTS = 5
ASSEMBLY_FEE_CENTS = 2500
HAUL_AWAY_FLAT_CENTS = 3000
WG_MULTIPLIER = 1.15

DISPOSAL_UNIT_LBS = 50
DISPOSAL_PER_UNIT_CENTS = 1000
REATTEMPT_FEE_CENTS = 2000

TEAM_PAYOUT_RATE = 0.375

LIABILITY_VALUE_UNIT_CENTS = 100000
DAMAGE_PENALTY = {"MINOR": 20, "MAJOR": 50}

MAX_REATTEMPTS = 2

# Dock / window defaults (PRD §3.1).
DEFAULT_DOCK_BUFFER_MIN = 30
DEFAULT_DOCK_SLOT_LENGTH_MIN = 60
