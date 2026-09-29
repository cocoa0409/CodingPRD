"""Named constants drawn from the API contract.

Thresholds, tolerances, weights and the canonical reference data used to build
preconditions. Nothing here is derived or guessed: each value is stated by the
contract.
"""

API_PREFIX = "/apportionment"

# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
CLOCK_INITIAL_UTC = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Mileage capture and reconstruction
# --------------------------------------------------------------------------
GAP_TOLERANCE_MILES = 5.0
LEG_MILEAGE_TOLERANCE_MILES = 0.5
RECONSTRUCTION_WINDOW_DAYS = 120
RECORD_RETENTION_DAYS = 1460
UNSUBSTANTIATED_AUDIT_FLAG_RATIO = 0.1500
RECONSTRUCTION_UPLIFT_FACTOR = 1.100

# --------------------------------------------------------------------------
# Quarterly settlement
# --------------------------------------------------------------------------
RECONSTRUCTED_MILEAGE_PENALTY_RATIO = 0.1000
PENALTY_RATE = 0.10
PENALTY_FLOOR_USD = 100.00

# --------------------------------------------------------------------------
# Registration apportionment
# --------------------------------------------------------------------------
ESTIMATED_DISTANCE_FLOOR_MILES = 20000.0
TRANSFER_ADMIN_FEE = 15.00

# --------------------------------------------------------------------------
# Credential distribution
# --------------------------------------------------------------------------
DRIVER_HANDOVER_BUFFER_DAYS = 2

# --------------------------------------------------------------------------
# Risk scoring
# --------------------------------------------------------------------------
RATIO_WEIGHT = 40
RATIO_SATURATION_RATIO = 0.25
MPG_WEIGHT = 25
MPG_INDUSTRY_BASELINE = 6.50
MPG_VARIANCE_BAND = 0.20
LATE_FILING_WEIGHT = 5
LATE_FILING_CAP = 3
RETENTION_WEIGHT = 20
RETENTION_SATURATION_COUNT = 4
RETENTION_PENALTY_WEIGHT = 30
AUDIT_SELECTION_THRESHOLD = 70
LICENSE_SUSPENSION_THRESHOLD = 90
RISK_SCORE_CAP = 100

# --------------------------------------------------------------------------
# Carrier defaults
# --------------------------------------------------------------------------
DEFAULT_BOND_CEILING_AMOUNT = 5000.00

# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# --------------------------------------------------------------------------
# Canonical reference data.
#
# Three jurisdictions: Illinois carries no surcharge, Indiana and Kentucky
# both do. The weight group W80 is declared at 80000 lbs everywhere.
# --------------------------------------------------------------------------
JURISDICTION_IL = {
    "jurisdiction_code": "IL",
    "name": "Illinois",
    "fuel_tax_rate_per_gallon": 0.6270,
    "surcharge_rate_per_gallon": 0.0000,
}
JURISDICTION_IN = {
    "jurisdiction_code": "IN",
    "name": "Indiana",
    "fuel_tax_rate_per_gallon": 0.3300,
    "surcharge_rate_per_gallon": 0.5500,
}
JURISDICTION_KY = {
    "jurisdiction_code": "KY",
    "name": "Kentucky",
    "fuel_tax_rate_per_gallon": 0.2460,
    "surcharge_rate_per_gallon": 0.0440,
}
CANONICAL_JURISDICTIONS = [JURISDICTION_IL, JURISDICTION_IN, JURISDICTION_KY]

WEIGHT_GROUP_W80 = "W80"
DECLARED_WEIGHT_W80_LBS = 80000

WEIGHT_GROUP_FEES_W80 = [
    {
        "jurisdiction_code": "IL",
        "weight_group_code": WEIGHT_GROUP_W80,
        "declared_weight_lbs": DECLARED_WEIGHT_W80_LBS,
        "annual_fee_amount": 2790.00,
    },
    {
        "jurisdiction_code": "IN",
        "weight_group_code": WEIGHT_GROUP_W80,
        "declared_weight_lbs": DECLARED_WEIGHT_W80_LBS,
        "annual_fee_amount": 1692.00,
    },
    {
        "jurisdiction_code": "KY",
        "weight_group_code": WEIGHT_GROUP_W80,
        "declared_weight_lbs": DECLARED_WEIGHT_W80_LBS,
        "annual_fee_amount": 1410.00,
    },
]

# The three credential types minted for each activated unit.
ALL_CREDENTIAL_TYPES = ["DECAL_SET", "CAB_CARD", "IFTA_LICENSE_COPY"]
CREDENTIALS_PER_VEHICLE = 3

REGISTRATION_YEAR = 2026
