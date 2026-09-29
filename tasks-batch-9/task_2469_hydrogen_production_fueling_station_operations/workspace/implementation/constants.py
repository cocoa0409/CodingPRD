"""Domain constants, all read from SCAFFOLD.yaml / PRD.md."""
from decimal import Decimal as D

# ---- roles (PRD 2.1 / scaffold 1.7) ----
ROLES = (
    "PlatformAdmin",
    "StationOperator",
    "ProductionEngineer",
    "QualityAnalyst",
    "SafetyOfficer",
    "ComplianceAdmin",
    "LogisticsDispatcher",
    "ProgramAuditor",
)

# ---- auth header names (PRD 2.1) ----
HDR_USER_ID = "X-User-ID"
HDR_USER_ROLE = "X-User-Role"

# ---- pagination (PRD 2.3) ----
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# ---- logical clock default (PRD 2.5) ----
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# ---- mass / pressure ----
KG_PER_L_PER_BAR = D("0.00008")

# ---- station_safety_posture ----
MIN_HIGH_BANK_DELIVERABLE_KG = D("10.000")

# ---- production_lot_carbon_intensity ----
H2_LHV_MJ_PER_KG = D("120.0")
COMPRESSION_ADDER_G_PER_KG = D("300.0")
NG_TOTAL_G_PER_MMBTU = D("61260.0")

# ---- purity_verdict ----
ANALYTE_ORDER = (
    "total_hydrocarbons_ppm",
    "water_ppm",
    "oxygen_ppm",
    "nitrogen_ppm",
    "carbon_monoxide_ppm",
    "carbon_dioxide_ppm",
    "total_sulfur_ppm",
    "ammonia_ppm",
    "helium_ppm",
)
REQUIRED_ANALYTES = ANALYTE_ORDER[:7]
OPTIONAL_ANALYTES = ("ammonia_ppm", "helium_ppm")
PURITY_LIMITS = {
    "total_hydrocarbons_ppm": D("2.000"),
    "water_ppm": D("5.000"),
    "oxygen_ppm": D("5.000"),
    "nitrogen_ppm": D("100.000"),
    "carbon_monoxide_ppm": D("0.200"),
    "carbon_dioxide_ppm": D("2.000"),
    "total_sulfur_ppm": D("0.004"),
    "ammonia_ppm": D("0.100"),
    "helium_ppm": D("300.000"),
}

# ---- required_precool_temperature ----
PRECOOL_TABLE = {
    "H70": {"HOT": D("-40.0"), "MILD": D("-33.0"), "COLD": D("-26.0")},
    "H35": {"HOT": D("-33.0"), "MILD": D("-26.0"), "COLD": D("-17.0")},
}
MC_FORMULA_RELIEF_C = D("5.0")

# ---- cascade_fill_allocation ----
TERMINAL_BAR = {"H35": D("438.00"), "H70": D("875.00")}
BANK_ORDER_CASCADE = ("HIGH", "MEDIUM", "LOW")
BANK_ORDER_MAKEUP = ("LOW", "MEDIUM", "HIGH")

# ---- dispense_metered_mass_correction ----
REF_TEMP_C = D("20.0")
REF_PRESSURE_BAR = D("700.00")
TEMP_COEFF_PER_C = D("0.00040")
PRESSURE_COEFF_PER_BAR = D("-0.00002")
METER_TOLERANCE_PCT = D("1.500")

# ---- delivery_net_receipt ----
DAILY_BOILOFF_RATE = D("0.003")

# ---- incentive_credit_netting ----
CI_BENCHMARK_GCO2E_PER_MJ = D("79.10")
EER = D("3.4")
ADMIN_TIER_HIGH_MT = D("3.600")
ADMIN_TIER_MID_MT = D("1.200")
ADMIN_RATE_HIGH = D("0.030")
ADMIN_RATE_MID = D("0.020")
ADMIN_RATE_LOW = D("0.010")

# ---- operational_thresholds ----
INSPECTION_GRACE_DAYS = 30
MIN_TRAINED_RESPONDERS = 2
MAX_RESCHEDULES = 2
MAX_REVISION_ROUNDS = 2
LOT_CONSUMED_FRACTION = D("0.900")
CONTRACT_CHANGEOVER_BUFFER_HOURS = 24

# ---- enums ----
UPTIME_METHODS = ("NOZZLE_WEIGHTED", "STATION_LEVEL")
PRESSURE_CLASSES = ("H35", "H70")
BANK_TIERS = ("HIGH", "MEDIUM", "LOW")
INSPECTION_STATUSES = ("CURRENT", "DUE", "OVERDUE", "CONDEMNED")
PATHWAYS = ("PEM_ELECTROLYSIS", "ALKALINE_ELECTROLYSIS", "SMR", "SMR_CCS")
ELECTROLYSIS_PATHWAYS = ("PEM_ELECTROLYSIS", "ALKALINE_ELECTROLYSIS")
QA_STATUSES = ("PENDING", "PASSED", "FAILED")
CI_STATUSES = ("PENDING", "CERTIFIED")
LOT_STATUSES = ("PRODUCED", "RELEASED", "REJECTED", "CONSUMED")
CI_VARIANTS = ("ANNUAL_AVERAGE", "HOURLY_MATCHED")
VERDICTS = ("PASS", "FAIL", "INDETERMINATE")
LEDGER_REASONS = (
    "OPENING_BALANCE",
    "DELIVERY_RECEIPT",
    "HEEL_RETURNED",
    "BOILOFF_LOSS",
    "DISPENSE_DRAW",
    "METER_CORRECTION",
    "METER_VOID_REVERSAL",
    "INSPECTION_VENT",
)
SOURCE_REF_TYPES = ("PRESSURE_VESSEL", "DELIVERY", "DISPENSE_SESSION")
DELIVERY_MODES = ("TUBE_TRAILER", "LIQUID_TANKER")
DELIVERY_STATUSES = ("SCHEDULED", "ARRIVED", "ACCEPTED", "REJECTED", "QUARANTINED")
REJECT_REASONS = ("PURITY_FAIL", "LOT_NOT_RELEASED", "DOCUMENTATION", "SEAL_BROKEN")
VEHICLE_CLASSES = ("LIGHT_DUTY", "TRANSIT_BUS", "HEAVY_TRUCK", "FORKLIFT")
FILL_PROTOCOLS = ("SAE_J2601_TABLE", "MC_FORMULA")
FILL_STATUSES = ("PRECOOLING", "FUELING", "COMPLETED", "ABORTED")
BILLING_STATUSES = ("PENDING", "METERED", "VOIDED")
ABORT_REASONS = ("OPERATOR_ABORT", "STATION_FROZEN")
VOID_REASONS = ("METER_FAULT", "BILLING_DISPUTE", "AUDIT_ADJUSTMENT")
SAFETY_KINDS = (
    "LEAK_DETECTED",
    "VENTILATION_FAULT",
    "COMPRESSOR_FAULT",
    "OVERPRESSURE",
    "SETBACK_BREACH",
)
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
DETECTED_BY = ("SENSOR", "OPERATOR_ROUND", "THIRD_PARTY")
SAFETY_STATUSES = ("OPEN", "ACKNOWLEDGED", "CLEARED")
CERT_TYPES = ("EMERGENCY_RESPONSE", "HAZMAT_AWARENESS", "CONFINED_SPACE")
PROGRAMS = ("LCFS", "CFP_OREGON", "CFS_CANADA")
CLAIM_STATUSES = (
    "SUBMITTED",
    "REVISION_REQUESTED",
    "CERTIFIED",
    "CREDITS_ISSUED",
    "DENIED",
)
REPORT_STATUSES = ("DRAFT", "FINAL", "AMENDED")
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
INSPECTION_OUTCOMES = ("PASS", "CONDEMN")
FREEZING_KINDS = ("LEAK_DETECTED", "VENTILATION_FAULT", "SETBACK_BREACH")
