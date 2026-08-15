"""Domain thresholds — numeric constants named in the PRD's calculation rules."""

# Logical clock default (PRD §2.5)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Hours-of-service thresholds (PRD §3.1) — all inclusive ("at the limit means
# exhausted / required").
SESSION_DRIVE_LIMIT_MIN = 660          # eleven hours
LONG_REST_MIN = 600                    # ten hours
DUTY_WINDOW_MIN = 840                  # fourteen hours
BREAK_REQUIRED_AFTER_DRIVE_MIN = 480   # eight hours
BREAK_QUALIFYING_MIN = 30
CYCLE_ON_DUTY_LIMIT_MIN = 4200         # seventy hours
CYCLE_WINDOW_MIN = 11520               # eight days

# Confinement and rest/unload (PRD §3.5)
MAX_CONFINEMENT_MIN = 1680             # twenty-eight hours, inclusive at arrive
REST_UNLOAD_MIN = 300                  # five hours, inclusive at resume

# Biosecurity washout (PRD §3.2)
WASHOUT_VALID_HOURS = 96               # inclusive boundary

# Brand inspection freshness (PRD §3.4)
BRAND_INSPECTION_VALID_HOURS = 96

# Backhaul linkage (PRD §3.3)
BACKHAUL_WINDOW_HOURS = 72             # inclusive
BACKHAUL_DISCOUNT = 0.85               # 15 percent discount

# Settlement (PRD §3.6, §3.8)
EXCESS_SHRINK_PENALTY_CENTS_PER_LB = 2.5
DISPUTE_WINDOW_HOURS = 48
SHIPPER_DEFAULT_SHRINK_PCT = 2.0

# Welfare fine schedule (PRD §3.7)
FINE_BASE_CENTS = {
    "INJURY": 33333,
    "DOWNER": 41667,
    "DEAD_ON_ARRIVAL": 100000,
    "ESCAPE": 25000,
}
FINE_SEVERITY_MULT = {
    "MINOR": 1.5,
    "MAJOR": 2.5,
    "CRITICAL": 4.0,
}
SUSPENSION_CRITICAL_COUNT = 2

# Weather thresholds by species (PRD §3.5), inclusive on both sides
HEAT_THRESHOLD_F = {"CATTLE": 95, "SWINE": 85, "SHEEP": 90, "HORSES": 95}
COLD_THRESHOLD_F = {"CATTLE": 0, "SWINE": 10, "SHEEP": -5, "HORSES": 5}
