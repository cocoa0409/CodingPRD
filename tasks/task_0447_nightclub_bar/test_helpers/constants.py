"""Domain thresholds — numeric constants from the PRD's calculations and defaults."""

# Venue creation defaults (PRD §3.1).
VENUE_DEFAULTS = {
    "LAST_CALL_OFFSET_MINUTES": 30,
    "COVER_BASE_CENTS": 2000,
    "COVER_SURGE_PCT": 0.5,
    "MAX_ALCOHOL_STRIKES": 4,
}

# Cover-charge surge band (PRD §3.4): surge applies when occupancy_count is at
# least ninety percent of fire_code_capacity (ceil of the fractional threshold).
SURGE_OCCUPANCY_FRACTION = 0.9

# ID-check gates (PRD §3.3): legal drinking age is 21, boundary inclusive.
LEGAL_DRINKING_AGE = 21

# Tab gratuity default (PRD §3.7).
DEFAULT_GRATUITY_PCT = 0.2

# Server logical-clock startup default (PRD §2.4).
CLOCK_STARTUP_DEFAULT = "2026-01-01T00:00:00Z"

# A syntactically valid UUID that resolves to no resource.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
