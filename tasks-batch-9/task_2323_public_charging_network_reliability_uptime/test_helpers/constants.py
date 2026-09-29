"""Domain thresholds and numeric constants stated by the PRD."""

# The logical clock's startup value (PRD 2.4).
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Pagination bounds (PRD 2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Interoperability score weights and the commissioning threshold (PRD 3.2, 3.3).
INTEROP = {
    "W_CONTACTLESS": 0.40,
    "W_PLUG_AND_CHARGE": 0.20,
    "W_PRICE_DISPLAY": 0.20,
    "W_ROAMING": 0.20,
    "COMMISSION_MIN_SCORE": 90.00,
    "ROAMING_COMPLIANT_VERSIONS": ["V2_2_1", "V2_3_0"],
}

# Response-deadline arithmetic (PRD 3.5).
FAULT_BASE_MINUTES = {
    "CRITICAL": 240,
    "MAJOR": 720,
    "MINOR": 2880,
    "INFORMATIONAL": 10080,
}

POWER_CLASS_FACTOR = {
    "DCFC_350": 0.50,
    "DCFC_150": 0.75,
    "L2_19": 1.00,
}

CORRIDOR_TIGHTEN_MINUTES = 60
REGULATORY_FLOOR_MINUTES = 120
REGULATORY_CAP_MINUTES = 4320

# Parts-hold promise (PRD 3.6).
MINUTES_PER_DAY = 1440

LABOR_MINUTES_BY_PART_CLASS = {
    "DISPENSER": 480,
    "POWER_MODULE": 300,
    "CABLE_ASSEMBLY": 180,
    "PAYMENT_TERMINAL": 120,
}

LABOR_MINUTES_DEFAULT = 120
EXPEDITE_TRIGGER_MINUTES = 2880
EXPEDITE_FACTOR = 0.50

# Uptime reporting (PRD 3.7).
MIN_REPORTING_PERIOD_MINUTES = 10080
UPTIME_PCT_MAX = 100.00

# Withhold tier ladder, walked from the top with an inclusive comparison
# (PRD 3.8).  Each entry is (minimum effective_uptime_pct, withhold_rate).
WITHHOLD_TIERS = [
    (97.00, 0.00),
    (95.00, 0.10),
    (90.00, 0.25),
    (0.00, 1.00),
]

# Values reused across setup chains so tests read in domain language.
TEST_DEFAULTS = {
    "COMMITTED_CAPACITY_KW": 400.00,
    "RATED_POWER_KW": 150.00,
    "TERMINAL_MODEL": "PT-9",
    "HOST_ORG_NAME": "Test Host Organisation",
    "ACCESS_OPEN_MINUTE_DEFAULT": 0,
    "ACCESS_CLOSE_MINUTE_DEFAULT": 1440,
}
