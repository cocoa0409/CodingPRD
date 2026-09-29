"""Domain constants for the hazardous waste TSDF API.

Every literal here is taken from the PRD: monetary constants in integer cents,
masses in kilograms, ratios as fractions, ppm and flash points with one decimal.
"""

# ─── Logical clock ────────────────────────────────────────────────────────────
CLOCK_START = "2026-08-01T00:00:00Z"

# ─── Financial assurance (PRD 3.2) ────────────────────────────────────────────
CLOSURE_BASE_FLOOR_CENTS = 25_000_000
CLOSURE_COST_PER_KG_CENTS = 1_800
TIER_1_CEILING_CENTS = 30_000_000
TIER_2_CEILING_CENTS = 60_000_000
CONTINGENCY_RATE_BY_TIER = {"TIER_1": 0.05, "TIER_2": 0.10, "TIER_3": 0.18}
CORRECTIVE_ACTION_RESERVE_PER_SNC_CENTS = 5_000_000

# ─── Generator reliability (PRD 3.3) ──────────────────────────────────────────
RELIABILITY_BASE = 100
RELIABILITY_DISCREPANCY_WEIGHT = 45
RELIABILITY_RETURN_WEIGHT = 35
RELIABILITY_PROFILE_FAIL_WEIGHT = 20
ROLLING_WINDOW_SIZE = 3
FULL_SAMPLE_RELIABILITY_FLOOR = 60

# ─── Sample tolerances (PRD 3.4) ──────────────────────────────────────────────
SAMPLE_TOLERANCES = {
    "FINGERPRINT": {"constituent": 0.15, "flash_point_c": 5.0, "ph": 1.0},
    "FULL": {"constituent": 0.10, "flash_point_c": 3.0, "ph": 0.5},
}
SAMPLE_ATTEMPT_LIMIT = 3

# ─── Acceptance charges (PRD 3.5) ─────────────────────────────────────────────
BASE_RATE_CENTS_PER_KG = {
    "BULK_LIQUID": 40,
    "SLUDGE": 55,
    "SOLID": 30,
    "LAB_PACK": 120,
}
HAZARD_MULTIPLIER = {
    "ACID": 1.10,
    "ALKALINE": 1.10,
    "OXIDIZER": 1.35,
    "CYANIDE_BEARING": 1.50,
    "WATER_REACTIVE": 1.45,
    "ORGANIC_SOLVENT": 1.20,
}
LDR_SURCHARGE_CENTS_PER_KG = 12
CONTAINER_HANDLING_FEE_CENTS = 750
BULK_VARIANCE_TOLERANCE = 0.10
CONTAINERISED_VARIANCE_TOLERANCE = 0.02
DISCREPANCY_REPORT_WINDOW_DAYS = 15

# ─── Containers and storage units (PRD 3.6, 3.7) ──────────────────────────────
HEADSPACE_MAX_FILL_RATIO = 0.95
TEN_DAY_LIMIT_DAYS = 10
INCOMPATIBLE_PAIRS = [
    ("ACID", "ALKALINE"),
    ("ACID", "CYANIDE_BEARING"),
    ("ACID", "WATER_REACTIVE"),
    ("OXIDIZER", "ORGANIC_SOLVENT"),
    ("OXIDIZER", "WATER_REACTIVE"),
    ("WATER_REACTIVE", "ALKALINE"),
]
AISLE_ENCROACHMENT_CM_PER_CONTAINER = 6
AISLE_MINIMUM_CM = 76.0
RESTRICTED_UTILIZATION_THRESHOLD = 0.9000
INSPECTION_FREQUENCY_CEILING_DAYS = {
    "CONTAINER_AREA": 7,
    "TEN_DAY_TRANSFER": 7,
    "TANK_SYSTEM": 1,
}

# ─── Treatment (PRD 3.8) ──────────────────────────────────────────────────────
TREATMENT_LIABILITY_CENTS_PER_KG = 220
DECONTAMINATION_BUFFER_MINUTES = 240
LDR_STANDARD_PPM = {"D008_LEAD": 750.0, "F001_SOLVENTS": 560.0}
LDR_IGNITABLE_FLASH_POINT_FLOOR_C = 60.0
RETREAT_LIMIT = 1

# ─── Air emissions and findings (PRD 3.9) ─────────────────────────────────────
LEAK_DEFINITION_PPM = {"LEVEL_1": 500.0, "LEVEL_2": 250.0, "LEVEL_3": 100.0}
FIRST_ATTEMPT_DUE_DAYS = 5
REPAIR_DUE_DAYS = 15
MAX_REPAIR_DELAY_DAYS = 180
DELAY_JUSTIFICATIONS = ["UNIT_SHUTDOWN_REQUIRED", "PART_UNAVAILABLE"]
FINDING_REOPEN_LIMIT = 2
FINDING_REOPEN_EXTENSION_DAYS = 30
OPEN_SNC_STATUSES = ["OPEN", "RESPONDED", "REOPENED"]

# ─── Pagination (PRD 2.3) ─────────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# ─── Test defaults shared by factories ────────────────────────────────────────
TEST_DEFAULTS = {
    "facility_name": "Ridgeline TSDF",
    "facility_epa_id": "TXD000111222",
    "permit_number": "TX-HW-0091",
    "permit_expires_at": "2027-06-30T00:00:00Z",
    "post_closure_cost_cents": 8_000_000,
    "max_concurrent_treatment_batches": 5,
    "generator_epa_id": "TXR000555666",
    "generator_name": "Bayou Coatings",
    "instrument_face_amount_cents": 90_000_000,
    "manifest_tracking_number": "MTN0000001",
    "transporter_epa_id": "TXT000999",
    "shipped_on": "2026-08-01",
}
