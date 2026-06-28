"""Domain thresholds — numeric constants from the PRD calculations and rules."""

# Drying / dry-standard determination (PRD §3.4)
DRY_TOLERANCE_PCT = 4  # is_dry when latest_moisture_content_pct <= dry_standard_pct + 4

# Psychrometric gpp (PRD §3.4)
P_ATM_HPA = 1013.25
GRAINS_PER_LB = 7000

# Equipment sizing (PRD §3.3)
AM_DIVISOR = {1: 100, 2: 70, 3: 60, 4: 50}      # sqft per air mover, keyed by sizing class
CLASS_FACTOR = {1: 0.5, 2: 1.0, 3: 1.5, 4: 2.0}  # ppd water load per sqft, keyed by class
WALL_PER_AM = 16                                  # linear ft of wet wall per air mover
FIRE_SMOKE_SIZING_CLASS = 2                       # FIRE/SMOKE jobs size at class 2

# Equipment day rates (PRD §3.5 / §3.7)
AM_DAY_RATE_CENTS = 2500
DEHU_DAY_RATE_CENTS = 8000

THRESHOLDS = {
    "DRY_TOLERANCE_PCT": DRY_TOLERANCE_PCT,
    "WALL_PER_AM": WALL_PER_AM,
    "AM_DAY_RATE_CENTS": AM_DAY_RATE_CENTS,
    "DEHU_DAY_RATE_CENTS": DEHU_DAY_RATE_CENTS,
}

# Logical clock startup default (PRD §2.4)
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"
