"""Domain thresholds — numeric constants from the PRD's calculations (§3).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# OBD-II verdict thresholds (PRD §3.4).
MAX_STORED_DTC = 0            # any stored DTC fails (dtc_count > 0 => FAIL)
MAX_INCOMPLETE_MONITORS = 1   # >1 incomplete readiness monitor fails (>=2 => FAIL)

# Fee components (PRD §3.6).
OBD_SURCHARGE_CENTS = 1000    # emissions surcharge for OBD-required classes
STATE_ENV_FEE_CENTS = 200     # flat state environmental fee, always added

# State remittance surcharge (PRD §3.12).
STATE_REMIT_RATE = 0.075      # 7.5% of the service portion, round-half-up per line

# Reinspection ceiling (PRD §3.9).
MAX_REINSPECTIONS = 3

# Default test values used across fixtures.
DEFAULT_REPAIR_COST_LIMIT_CENTS = 60000
DEFAULT_PASSENGER_BASE_FEE_CENTS = 2500
DEFAULT_MOTORCYCLE_BASE_FEE_CENTS = 1500
DEFAULT_REINSPECTION_WINDOW_DAYS = 30

# A syntactically valid VIN (exactly 17 uppercase alphanumerics) for setup.
DEFAULT_VIN = "1HGCM82633A004352"
SECONDARY_VIN = "2HGCM82633A004353"
MOTORCYCLE_VIN = "JH2SC82A4MM100001"
HEAVY_DUTY_VIN = "1FTFW1ET5DFC10312"
