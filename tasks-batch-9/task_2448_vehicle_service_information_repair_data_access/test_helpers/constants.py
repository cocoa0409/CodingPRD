"""Domain constants and thresholds taken from the PRD."""

# --- Logical clock -----------------------------------------------------------
# Before any clock-setting call the logical clock reads exactly this instant.
INITIAL_CLOCK = "2026-08-01T00:00:00Z"
SECONDS_PER_DAY = 86400
DAYS_PER_MONTH = 30

# --- Pricing parity ---------------------------------------------------------
PARITY_MAX_INDEX = 1.15
PARITY_INDEX_DECIMALS = 4

# --- Entitlement charge -----------------------------------------------------
TIER_MULT = {"BASIC": 1.00, "PRO": 0.85, "ENTERPRISE": 0.70}
SEAT_FACTOR_INCLUDED_SEATS = 3
SEAT_FACTOR_STEP = 0.05

# --- Gateway access fee -----------------------------------------------------
SESSION_BASE_CENTS = 2500
VIN_CREDENTIAL_CENTS = 300
JOB_TYPE_CENTS = {
    "IMMOBILIZER_KEY": 4000,
    "MODULE_FLASH": 3000,
    "ADAS_CALIBRATION": 6000,
}
DISCOUNT_TIER_1_CENTS = 5000
DISCOUNT_TIER_2_CENTS = 10000
DISCOUNT_RATE_TIER_0 = 0.00
DISCOUNT_RATE_TIER_1 = 0.05
DISCOUNT_RATE_TIER_2 = 0.10
SURCHARGE_RATE_IMMOBILIZER = 0.12
SURCHARGE_RATE_STANDARD = 0.04

# --- Coverage completeness --------------------------------------------------
COVERAGE_PCT_DECIMALS = 2
EMPTY_COVERAGE_PCT = 0.00

# --- Interval conventions ---------------------------------------------------
ENTITLEMENT_COOLDOWN_HOURS = 24

# --- Pagination -------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Secure-gateway credential ---------------------------------------------
CREDENTIAL_TOKEN_PREFIX = "GW-"
CREDENTIAL_TOKEN_HEX_LEN = 8
CREDENTIAL_TOKEN_PATTERN = r"^GW-[0-9A-F]{8}$"

# --- Sample VINs (17 chars, uppercase, no I/O/Q) ----------------------------
VIN_PRIMARY = "1HGCM82633A004352"
VIN_SECONDARY = "1HGCM82633A004353"
VIN_TERTIARY = "2T1BURHE0JC001234"

# --- System area catalogue used across the suite ----------------------------
SYSTEM_AREA_SPECS = {
    "ADAS": {
        "code": "ADAS",
        "name": "Advanced Driver Assistance",
        "requires_calibration_doc": True,
        "requires_security_credential": True,
    },
    "POWERTRAIN": {
        "code": "POWERTRAIN",
        "name": "Powertrain",
        "requires_calibration_doc": False,
        "requires_security_credential": True,
    },
    "BODY_ELECTRICAL": {
        "code": "BODY_ELECTRICAL",
        "name": "Body Electrical",
        "requires_calibration_doc": False,
        "requires_security_credential": False,
    },
}

# --- Reference commercial figures used by the fixtures ----------------------
# Manufacturer priced exactly at the parity ceiling under the list basis.
PARITY_BOUNDARY_INDEPENDENT_CENTS = 115000
PARITY_BOUNDARY_INDEPENDENT_SYSTEMS = 3
PARITY_BOUNDARY_DEALER_CENTS = 100000
PARITY_BOUNDARY_DEALER_SYSTEMS = 4

LICENSE_MONTHLY_FEE_CENTS = 100000
LICENSE_PER_VEHICLE_FEE_CENTS = 2500
LICENSE_SEAT_CAP = 5

DEFAULT_FUNDING_CENTS = 200000
DEFAULT_ENTITLEMENT_WINDOW_START = "2026-08-01T00:00:00Z"
DEFAULT_ENTITLEMENT_WINDOW_END = "2026-09-01T00:00:00Z"
DEFAULT_LICENSE_EFFECTIVE_START = "2026-08-01T00:00:00Z"
DEFAULT_LICENSE_EFFECTIVE_END = "2027-08-01T00:00:00Z"
DEFAULT_SESSION_WINDOW_START = "2026-08-03T09:00:00Z"
DEFAULT_SESSION_WINDOW_END = "2026-08-03T12:00:00Z"
DEFAULT_CREDENTIAL_EXPIRY = "2026-12-31T00:00:00Z"
DEFAULT_ATTESTATION_EXPIRY = "2026-12-31T00:00:00Z"
