"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock: before any call sets it, the clock reads exactly this instant.
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Gowning qualification validity: qualified_at + 365 days.
QUALIFICATION_VALID_DAYS = 365

# Cleaning validation: default required passes when the field is omitted.
DEFAULT_REQUIRED_CONSECUTIVE_PASSES = 3

# Excursion severity scoring constants.
VIABLE_BASE_WEIGHT = 10
PARTICLE_BASE_WEIGHT = 4
ZONE_MULTIPLIERS = {"ISO_5": 3, "ISO_6": 2.5, "ISO_7": 2, "ISO_8": 1}
RECURRENCE_WEIGHT = 0.25
RECURRENCE_WINDOW_DAYS = 30

# Common room limit profiles used across scenarios.
ISO7_PARTICLE_ALERT = 300000
ISO7_PARTICLE_ACTION = 352000
ISO7_VIABLE_ALERT = 50
ISO7_VIABLE_ACTION = 100
ISO8_PARTICLE_ALERT = 3500000
ISO8_PARTICLE_ACTION = 3520000
ISO8_VIABLE_ALERT = 100
ISO8_VIABLE_ACTION = 200
ISO5_PARTICLE_ALERT = 100000
ISO5_PARTICLE_ACTION = 352000
ISO5_VIABLE_ALERT = 10
ISO5_VIABLE_ACTION = 20

TEST_DEFAULTS = {
    "RECERT_INTERVAL_DAYS": 180,
}
