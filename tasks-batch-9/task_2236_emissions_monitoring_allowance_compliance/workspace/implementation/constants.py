"""Enumerations, role names and physical constants taken from PRD sections 2-3."""

from decimal import Decimal

API_PREFIX = "/emissions"

# --- roles (PRD 2.1) --------------------------------------------------------
ROLE_REGULATORY_REVIEWER = "RegulatoryReviewer"
ROLE_FACILITY_OPERATOR = "FacilityOperator"
ROLE_QA_ANALYST = "QAAnalyst"
ROLE_PREPARER = "EmissionsReportPreparer"
ROLE_DESIGNATED_REP = "DesignatedRepresentative"
ROLE_ALLOWANCE_TRADER = "AllowanceTrader"

ALL_ROLES = (
    ROLE_REGULATORY_REVIEWER,
    ROLE_FACILITY_OPERATOR,
    ROLE_QA_ANALYST,
    ROLE_PREPARER,
    ROLE_DESIGNATED_REP,
    ROLE_ALLOWANCE_TRADER,
)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# --- programs / pollutants --------------------------------------------------
PROGRAMS = ("ARP_SO2", "CSAPR_NOX_ANNUAL", "CSAPR_NOX_OZONE", "CSAPR_SO2_G1")

PROGRAM_POLLUTANT = {
    "ARP_SO2": "SO2",
    "CSAPR_SO2_G1": "SO2",
    "CSAPR_NOX_ANNUAL": "NOX_RATE",
    "CSAPR_NOX_OZONE": "NOX_RATE",
}

FACILITY_STATUSES = ("OPERATING", "RETIRED")
COMPLIANCE_POSTURES = ("COMPLIANT", "WATCH", "DEFICIT")

# --- unit -------------------------------------------------------------------
FUEL_TYPES = ("COAL", "NATURAL_GAS", "OIL")
CONTROL_DEVICES = ("SCR", "SNCR", "FGD", "NONE")
OUTAGE_DEVICES = ("SCR", "SNCR", "FGD")
DISPATCH_STATES = ("OFFLINE", "ONLINE", "RESERVE_SHUTDOWN")
CONTROL_STATUSES = ("AVAILABLE", "DEGRADED", "OUT_OF_SERVICE")

# The only four dispatch moves the PRD declares (3.1).
ALLOWED_DISPATCH_MOVES = {
    ("OFFLINE", "ONLINE"),
    ("RESERVE_SHUTDOWN", "ONLINE"),
    ("ONLINE", "RESERVE_SHUTDOWN"),
    ("ONLINE", "OFFLINE"),
}

# --- monitoring system ------------------------------------------------------
PARAMETERS = ("SO2", "NOX_RATE", "CO2", "FLOW")
SYSTEM_TYPES = ("CEM", "FLOW_MONITOR", "EXCEPTED_APPENDIX_D")
QA_STATUSES = (
    "RECERTIFICATION_PENDING",
    "CONDITIONALLY_VALID",
    "CERTIFIED",
    "OUT_OF_CONTROL",
    "RETIRED",
)
CAL_STATUSES = ("CAL_CURRENT", "CAL_EXPIRED", "CAL_FAILED")
QA_ACTIONS = ("CONDITIONALLY_VALIDATE", "CERTIFY", "DECLARE_OUT_OF_CONTROL", "RETIRE")
CALIBRATION_RESULTS = ("PASSED", "FAILED", "OUT_OF_CONTROL_TRIGGERED")

CALIBRATION_STALE_HOURS = 26

# --- RATA -------------------------------------------------------------------
RATA_STATUSES = ("SCHEDULED", "RUNS_RECORDED", "PASSED", "FAILED", "VOIDED")
RA_BASES = ("REFERENCE_MEAN", "APPLICABLE_STANDARD")

T_VALUES = {
    9: Decimal("1.860"),
    10: Decimal("1.833"),
    11: Decimal("1.812"),
    12: Decimal("1.796"),
}

RATA_MIN_RUNS = 9
RATA_MAX_RUNS = 12
RATA_PASS_THRESHOLD = Decimal("10.0")

# Low-emitter thresholds that unlock APPLICABLE_STANDARD (PRD 3.3).
LOW_EMITTER_THRESHOLD = {
    "SO2": Decimal("0.300"),
    "NOX_RATE": Decimal("0.300"),
    "FLOW": Decimal("0.300"),
    "CO2": Decimal("5.000"),
}

# --- fuel sample ------------------------------------------------------------
FUEL_SAMPLE_STATUSES = ("PENDING", "ANALYZED", "INVALIDATED")
FUEL_ANALYSIS_OUTCOMES = ("ANALYZED", "INVALIDATE")
ANALYSIS_METHODS = ("ASTM_D5865", "ASTM_D4239", "GC_D1945")

# --- operating hours --------------------------------------------------------
HEAT_INPUT_METHODS = ("CEMS_FLOW_CO2", "APPENDIX_D_FUEL")
DATA_QUALITIES = ("MEASURED", "SUBSTITUTED", "UNAVAILABLE")
SUBSTITUTION_METHODS = (
    "NONE",
    "T1_90TH_PERCENTILE",
    "T2_95TH_PERCENTILE",
    "T3_LOOKBACK_MAXIMUM",
    "T4_MAX_POTENTIAL_CONCENTRATION",
)

CEMS_REQUIRED_FIELDS = ("flow_scfh", "co2_conc_pct", "so2_conc_ppm")
CEMS_FORBIDDEN_FIELDS = ("fuel_flow_lbs", "fuel_sample_id")
APPENDIX_D_REQUIRED_FIELDS = ("fuel_flow_lbs", "fuel_sample_id")
APPENDIX_D_FORBIDDEN_FIELDS = ("flow_scfh", "co2_conc_pct", "so2_conc_ppm")

METHOD_SYSTEM_TYPES = {
    "CEMS_FLOW_CO2": ("CEM", "FLOW_MONITOR"),
    "APPENDIX_D_FUEL": ("EXCEPTED_APPENDIX_D",),
}

SO2_CEMS_FACTOR = Decimal("0.000000166")
CO2_CEMS_FACTOR = Decimal("0.1194")
CEMS_HEAT_INPUT_DIVISOR = Decimal("1800.0")
APPENDIX_D_SO2_FACTOR = Decimal("2.0")
APPENDIX_D_CO2_FACTOR = Decimal("205.3")
LBS_PER_TON = Decimal("2000")
MMBTU_PER_MILLION_BTU = Decimal("1000000")

BULK_MIN_HOURS = 1
BULK_MAX_HOURS = 200

# --- missing data substitution ---------------------------------------------
LOOKBACK_SIZE = 20
MAX_POTENTIAL_CONCENTRATION_PPM = 400
AVAILABILITY_FLOOR = Decimal("80.0")
TIER1_AVAILABILITY = Decimal("95.0")
TIER2_AVAILABILITY = Decimal("90.0")
TIER3_AVAILABILITY = Decimal("80.0")
PERCENTILE_90 = Decimal("0.90")
PERCENTILE_95 = Decimal("0.95")

# --- quarterly report -------------------------------------------------------
REPORT_STATUSES = ("DRAFT", "VALIDATED", "SUBMITTED", "CERTIFIED", "REJECTED", "ACCEPTED")
SUBMISSION_FORMATS = ("XML_ECMPS", "JSON_ECMPS")
REPORT_DECISIONS = ("ACCEPT", "REJECT")
MIN_REPORT_YEAR = 2000
MIN_STATEMENT_LENGTH = 10

CERTIFICATION_STATUSES = ("SIGNED", "REVOKED")

# --- permit limits ----------------------------------------------------------
POLLUTANTS = ("SO2", "NOX_RATE", "CO2")
LIMIT_UNITS = ("LB_PER_MMBTU", "LB_PER_HR", "TONS_PER_YEAR")
AVERAGING_BASES = ("ROLLING_3_HOUR", "ROLLING_30_DAY", "ANNUAL")
EVALUATION_STATUSES = ("NOT_EVALUATED", "IN_COMPLIANCE", "EXCEEDED", "INSUFFICIENT_DATA")

WINDOW_SPAN_HOURS = {
    "ROLLING_3_HOUR": 3,
    "ROLLING_30_DAY": 720,
    "ANNUAL": 8760,
}
WINDOW_MIN_SAMPLES = {
    "ROLLING_3_HOUR": 3,
    "ROLLING_30_DAY": 24,
    "ANNUAL": 24,
}

EXCESS_EVENT_STATUSES = ("DETECTED", "REPORTED", "UNDER_REVIEW", "EXCUSED", "ENFORCEABLE", "WITHDRAWN")
EXCESS_EVENT_DECISIONS = ("RETURN", "EXCUSE", "ENFORCE")

# --- allowances -------------------------------------------------------------
ACCOUNT_STATUSES = ("OPEN", "TRUE_UP_LOCKED", "CLOSED")
TRANSACTION_TYPES = ("PURCHASE", "TRANSFER_IN", "TRANSFER_OUT", "SURRENDER", "PENALTY_DEDUCTION")
TRANSACTION_STATUSES = ("PROPOSED", "RECORDED", "SETTLED", "REVERSED")
TRANSACTION_ORIGINS = ("MANUAL", "TRUE_UP_SURRENDER", "TRUE_UP_PENALTY")
TRANSACTION_ACTIONS = ("RECORD", "SETTLE", "REVERSE")
TRANSFER_TYPES = ("TRANSFER_OUT", "TRANSFER_IN")
PENALTY_MULTIPLIER = Decimal("2.0")
MIN_COMPLIANCE_YEAR = 2000

# --- control outages --------------------------------------------------------
OUTAGE_TYPES = ("PLANNED_MAINTENANCE", "FORCED", "RATA_TEST_BYPASS")
OUTAGE_STATUSES = ("PLANNED", "ACTIVE", "CLOSED", "CANCELLED")
OUTAGE_ACTIONS = ("ACTIVATE", "CLOSE", "CANCEL")
DEFAULT_MAX_CONCURRENT_OUTAGES = 2
