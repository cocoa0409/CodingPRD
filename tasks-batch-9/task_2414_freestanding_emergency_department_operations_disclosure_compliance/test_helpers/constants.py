"""Domain constants and canonical payload defaults drawn from the PRD narrative."""

# --------------------------------------------------------------- the clock ---
# PRD 2.4: before the clock has ever been set it reads 2026-08-01T00:00:00Z.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"
# Every fixture pins the clock to a fixed working instant so date-window
# statuses (payer contract, transfer agreement, ambulance memorandum) and the
# 30-minute screening deadline are deterministic.
DEFAULT_CLOCK = "2026-08-01T08:00:00Z"

# ------------------------------------------------------------ enumerations ---
LICENSE_CATEGORIES = ("INDEPENDENT_FREESTANDING_ED", "HOSPITAL_OUTPATIENT_DEPARTMENT_OFF_CAMPUS")
LICENSE_STATUSES = ("ACTIVE", "PROBATION", "SUSPENDED")
POSTURES = ("OPEN", "RESTRICTED", "SUSPENDED")
IMAGING_CODES = ("XRAY", "CT", "ULTRASOUND", "MRI")
LAB_CODES = ("CBC", "CHEMISTRY", "TROPONIN", "BLOOD_CULTURE")
PHARMACY_CODES = ("ANALGESIC", "ANTIBIOTIC", "THROMBOLYTIC")
ALL_ANCILLARY_CODES = IMAGING_CODES + LAB_CODES + PHARMACY_CODES
SERVICE_LINES = ("GENERAL_MEDICAL", "CARDIAC", "STROKE", "TRAUMA", "PEDIATRIC", "PSYCHIATRIC")
SIGNAGE_ELEMENTS = (
    "LICENSE_CATEGORY_SIGN",
    "FEE_DISCLOSURE_SIGN",
    "NETWORK_STATUS_SIGN",
    "NOT_A_URGENT_CARE_SIGN",
)
ALL_SIGNAGE_ELEMENTS = list(SIGNAGE_ELEMENTS)
# PRD 3.1: an INDEPENDENT_FREESTANDING_ED must post all four elements, while a
# HOSPITAL_OUTPATIENT_DEPARTMENT_OFF_CAMPUS must post the first three.
REQUIRED_SIGNAGE_BY_CATEGORY = {
    "INDEPENDENT_FREESTANDING_ED": list(SIGNAGE_ELEMENTS),
    "HOSPITAL_OUTPATIENT_DEPARTMENT_OFF_CAMPUS": list(SIGNAGE_ELEMENTS[:3]),
}
LEDGER_EVENT_TYPES = (
    "DISCLOSURE_PRESENTED",
    "DISCLOSURE_ACKNOWLEDGED",
    "DISCLOSURE_REFUSED",
    "DISCLOSURE_DEFECT",
    "EMERGENT_WAIVER_RECORDED",
    "SCREENING_DELAY",
    "TEMPLATE_PUBLISHED",
    "SIGNAGE_ATTESTED",
    "POSTURE_CHANGE",
    "TRANSFER_DECLINED_FOR_INSURANCE",
    "BALANCE_BILL_ISSUED",
    "IDR_INITIATED",
    "IDR_AWARDED",
    "IDR_AWARD_WITHDRAWN",
)
DEFECT_COUNTED_EVENT_TYPES = (
    "DISCLOSURE_REFUSED",
    "DISCLOSURE_DEFECT",
    "SCREENING_DELAY",
    "TRANSFER_DECLINED_FOR_INSURANCE",
)

# ------------------------------------------------- good-faith estimate -------
# PRD 3.6: the allowance is 15000 cents at acuity 1 ... 220000 cents at acuity 5.
ACUITY_ALLOWANCE_CENTS = {1: 15000, 2: 35000, 3: 70000, 4: 130000, 5: 220000}
ESTIMATE_TIER_B_THRESHOLD_CENTS = 100000
ESTIMATE_TIER_C_THRESHOLD_CENTS = 250000
ESTIMATE_TIER_A_RATE = 0.00
ESTIMATE_TIER_B_RATE = 0.05
ESTIMATE_TIER_C_RATE = 0.09

# ----------------------------------------------- ancillary price schedule ----
# PRD 3.7: the fixed unit-charge schedule, in whole cents.
ANCILLARY_UNIT_CHARGE_CENTS = {
    "XRAY": 12000,
    "CT": 49000,
    "ULTRASOUND": 24000,
    "MRI": 145000,
    "CBC": 4500,
    "CHEMISTRY": 6200,
    "TROPONIN": 15500,
    "BLOOD_CULTURE": 11500,
    "ANALGESIC": 8500,
    "ANTIBIOTIC": 7400,
    "THROMBOLYTIC": 210000,
}
ANCILLARY_CATEGORY_BY_CODE = {
    **{code: "IMAGING" for code in IMAGING_CODES},
    **{code: "LABORATORY" for code in LAB_CODES},
    **{code: "PHARMACY" for code in PHARMACY_CODES},
}

# ------------------------------------------------ coverage and forecasting ---
FORECAST_WINDOW_DAYS = 14
PATIENTS_PER_PHYSICIAN_HOUR = 1.5
COVERAGE_FLOOR_HOURS_PER_DAY = 12
BOARD_CERT_MIN_SHARE = 0.75
PEAK_WEIGHT = 0.60
MEAN_WEIGHT = 0.40

# ------------------------------------------------------- compliance gates ----
DEFECT_RESTRICT_THRESHOLD = 3
SIGNAGE_VALIDITY_DAYS = 365
MSE_START_DEADLINE_MINUTES = 30
STATE_BENCHMARK_RATE = 0.80

# PRD 2.8: restricted_service_codes by posture.
RESTRICTED_CODES_WHEN_OPEN = []
RESTRICTED_CODES_WHEN_RESTRICTED = ["MRI", "THROMBOLYTIC"]
RESTRICTED_CODES_WHEN_SUSPENDED = list(ALL_ANCILLARY_CODES)

# PRD 3.8: acuity 1 and 2 require tier 1, acuity 3 tier 2, acuity 4 tier 3,
# acuity 5 tier 4; acuity 4 requires ALS or CRITICAL_CARE and acuity 5 requires
# CRITICAL_CARE transport.
ACUITY_MIN_CAPABILITY_TIER = {1: 1, 2: 1, 3: 2, 4: 3, 5: 4}
ACUITY_MIN_LEVEL_OF_CARE = {4: ("ALS", "CRITICAL_CARE"), 5: ("CRITICAL_CARE",)}

THRESHOLDS = {
    "DEFECT_RESTRICT_THRESHOLD": DEFECT_RESTRICT_THRESHOLD,
    "MSE_START_DEADLINE_MINUTES": MSE_START_DEADLINE_MINUTES,
    "SIGNAGE_VALIDITY_DAYS": SIGNAGE_VALIDITY_DAYS,
    "NEGOTIATION_ROUND_BOUND": 3,
    "COVERAGE_FLOOR_HOURS_PER_DAY": COVERAGE_FLOOR_HOURS_PER_DAY,
    "PAGINATION_LIMIT_DEFAULT": 10,
    "PAGINATION_LIMIT_MAX": 100,
}

# ------------------------------------------------ canonical payload values ---
TEST_DEFAULTS = {
    "CLOCK": DEFAULT_CLOCK,
    "FACILITY_NAME": "Cedar Freestanding ED",
    "STATE_CODE": "TX",
    "TEMPLATE_FACILITY_FEE_CENTS": 145000,
    "TEMPLATE_OBSERVATION_HOURLY_CENTS": 42000,
    "PAYER_NAME": "Lone Star Health",
    "QPA_CENTS": 190000,
    "COINSURANCE_RATE": 0.20,
    "DEDUCTIBLE_REMAINING_CENTS": 50000,
    "CONTRACT_START": "2026-07-01",
    "CONTRACT_END": "2026-12-31",
    "DESTINATION_HOSPITAL": "Trinity Regional Hospital",
    "SECOND_DESTINATION_HOSPITAL": "Bluff Creek Medical Center",
    "CARRIER_NAME": "Brazos EMS",
    "MOU_COVERAGE_START": "2026-07-01T00:00:00Z",
    "MOU_COVERAGE_END": "2026-12-31T00:00:00Z",
}

# The canonical billed bundle the settlement narratives are worked against:
# a facility fee of 145000 plus CT x2 (98000), TROPONIN x2 (31000) and
# ANALGESIC x1 (8500), billed_total 282500.
CANONICAL_ANCILLARY_LINES = (
    {"category": "IMAGING", "code": "CT", "quantity": 2},
    {"category": "LABORATORY", "code": "TROPONIN", "quantity": 2},
    {"category": "PHARMACY", "code": "ANALGESIC", "quantity": 1},
)
CANONICAL_BILLED_TOTAL_CENTS = 282500
CANONICAL_BILLED_ANCILLARY_CENTS = 137500
