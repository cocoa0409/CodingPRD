"""Domain thresholds — numeric constants from the PRD's calculations (§3.1–§3.5)."""

# Priority-score weights (PRD §3.2)
SEVERITY_BASE = {"LOW": 10, "MEDIUM": 25, "HIGH": 50, "SEVERE": 80}
SURFACE_VISIBILITY = {"SIGN": 1.5, "WALL": 1.2, "VEHICLE": 1.1, "FENCE": 1.0, "SIDEWALK": 0.8}
OFFENSIVE_BONUS = 40
PUBLIC_PRIORITY_ADJ = 5
HOTSPOT_MULT = {"HOTSPOT": 1.5, "MONITORED": 1.2, "NORMAL": 1.0}

# Abatement-cost rates (PRD §3.3, §2.6)
LABOR_RATE_CENTS_PER_HOUR = 6500
ADMIN_FEE_PCT = 0.15

# Hotspot severity index weights (PRD §3.1)
SEVERITY_WEIGHT = {"LOW": 1, "MEDIUM": 2, "HIGH": 4, "SEVERE": 8}
WINDOW_DAYS = 90

# Site abatement buffer for PRIVATE sites (PRD §3.3)
SITE_BUFFER_HOURS = 24

# Logical-clock startup default (PRD §2.5)
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"

# Pagination defaults (PRD §2.3)
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

TEST_DEFAULTS = {
    "UNIT_COST_CENTS": 1200,
    "QUANTITY_AVAILABLE": 10.0,
    "EST_LABOR_HOURS": 2.5,
    "ACTUAL_LABOR_HOURS": 3.0,
    "RESERVE_QTY": 3.0,
}
