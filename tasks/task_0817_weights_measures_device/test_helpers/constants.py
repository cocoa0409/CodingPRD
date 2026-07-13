"""Domain thresholds — numeric constants from the PRD calculations (§2.9, §3.2, §3.5–§3.7)."""

# Server startup default logical clock (PRD §2.9). Q1 -> proration factor 1.00.
DEFAULT_CLOCK_UTC = "2026-03-01T00:00:00Z"

# Registration fee base amounts per device_type (PRD §3.2).
BASE_FEE_CENTS = {
    "SCALE": 12000,
    "FUEL_PUMP": 8000,
    "SCANNER": 15000,
}

# Quarter proration factors keyed on registration month (PRD §3.2).
QUARTER_FACTOR = {
    1: 1.00, 2: 1.00, 3: 1.00,     # Q1
    4: 0.75, 5: 0.75, 6: 0.75,     # Q2
    7: 0.50, 8: 0.50, 9: 0.50,     # Q3
    10: 0.25, 11: 0.25, 12: 0.25,  # Q4
}

# Accuracy maintenance tolerances (grams) per device_class and load tier (PRD §3.5).
# Acceptance tolerance = maintenance / 2 for a REGISTERED (never-sealed) device.
MAINT_TOL = {
    "CLASS_III": {"load<=5000": 6, "5000<load<=20000": 12, "load>20000": 20},
    "CLASS_IIIL": {"load<=10000": 10, "10000<load<=50000": 20, "load>50000": 40},
}

# Scanner audit thresholds (PRD §3.6).
MAX_ERRORS = 2       # outcome FAIL when mispriced-item count is strictly greater than 2
MIN_SAMPLE = 1       # at least one audit item required to finalize a price verification

# Penalty amounts (PRD §3.7).
PENALTY_RATE = 1.5
BASE_PENALTY_CENTS = {
    "OUT_OF_TOLERANCE": 5000,
    "PRICE_ERROR": 0,
    "OPERATING_CONDEMNED": 20000,
}

# Device re-test buffer in minutes (PRD §3.3).
DEVICE_BUFFER_MINUTES = 60
