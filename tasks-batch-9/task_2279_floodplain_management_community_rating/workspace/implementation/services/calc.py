"""Domain constants and the pure numeric primitives (SCAFFOLD 1.3, PRD 2.6)."""

from decimal import Decimal, ROUND_HALF_UP

D = Decimal
ZERO = D("0")

# --- structure_improvement_aggregates
MIN_COUNTED_COST_USD = D("500.00")

# --- substantial_ratio
SI_THRESHOLD_PCT = D("50.00")

# --- required_lowest_floor_elevation
ZONE_MIN_FREEBOARD_FT = {"A": D("1.0"), "AE": D("1.0"), "AO": D("1.0"), "VE": D("2.0")}
SI_ADDITIONAL_FREEBOARD_FT = D("0.5")
FLOODPROOFING_CREDIT_FT = D("1.0")

# --- certificate_datum_normalization
DATUM_OFFSET_FT = {"NAVD88": D("0.0"), "NGVD29": D("-0.85")}

# --- repetitive_loss_classification
RL_CLAIM_MIN_PAID_USD = D("1000.00")
RL_WINDOW_YEARS = 10
RL_REPETITIVE_CLAIM_COUNT = 2
RL_SEVERE_CLAIM_COUNT = 4

# --- outreach_coverage_and_credit
OUTREACH_FULL_CREDIT_PCT = D("90.00")
OUTREACH_PARTIAL_CREDIT_PCT = D("75.00")
A330_FULL_POINTS = 50
A330_PARTIAL_POINTS = 25

# --- higher_standard_credit
A430_POINTS_PER_FOOT = 100
A430_FREEBOARD_CAP_FT = D("5.0")
A430_CUMULATIVE_POINTS = 90
A420_POINTS_PER_AREA = 50
A420_POINTS_CAP = 200
A510_POINTS = 60

# --- crs_class_determination
CRS_POINTS_PER_CLASS = 500
BEST_CRS_CLASS = 1
WORST_CRS_CLASS = 10

# --- sanction_risk_and_posture
SEVERITY_WEIGHT = {"MINOR": 2, "MAJOR": 6, "CRITICAL": 12}
DEFAULTED_ORDER_PENALTY_POINTS = 5
A510_PROBATION_CREDIT_POINTS = 4
PROBATION_THRESHOLD_POINTS = 10
SUSPENSION_THRESHOLD_POINTS = 25

# --- derived_deadlines_and_loop_limits
PERMIT_VALIDITY_DAYS = 365
DOC_RETENTION_REVIEW_YEARS = 5
APPEAL_WINDOW_DAYS = 30
DOC_CYCLE_YEARS = 5
SWEEP_BUFFER_DAYS = 7
VERIFICATION_VISIT_YEAR_MODULUS = 5
MAX_REVISION_ROUNDS = 3
MAX_ORDER_EXTENSIONS = 2

# --- enums
FLOOD_ZONES = ("A", "AE", "AO", "VE", "X")
PANEL_STATUSES = ("PENDING_REVISION", "EFFECTIVE", "SUPERSEDED")
STRUCTURE_USES = ("RESIDENTIAL", "NON_RESIDENTIAL", "ACCESSORY")
PROJECT_TYPES = ("NEW_CONSTRUCTION", "IMPROVEMENT", "REPAIR")
CERTIFICATE_TYPES = ("CONSTRUCTION_DRAWINGS", "BUILDING_UNDER_CONSTRUCTION",
                     "FINISHED_CONSTRUCTION")
DATUMS = ("NAVD88", "NGVD29")
RECORD_TYPES = ("IMPROVEMENT", "DAMAGE", "REVERSAL")
METHODS = ("SINGLE_EVENT", "CUMULATIVE")
VIOLATION_TYPES = ("NO_PERMIT", "ELEVATION_DEFICIENT", "MISSING_CERTIFICATE",
                   "UNPERMITTED_FILL")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
ACTIVITY_CODES = ("A430_FREEBOARD", "A430_CUMULATIVE_SI", "A420_OPEN_SPACE",
                  "A510_HIGHER_STD_ENFORCEMENT", "A330_OUTREACH")

ACTIVE_VIOLATION_STATUSES = ("OPEN", "ORDER_ISSUED", "ESCALATED")
LIVE_PERMIT_STATUSES = ("UNDER_REVIEW", "REVISION_REQUIRED", "APPROVED")
RESOLVED_CASE_STATUSES = ("DETERMINED", "APPEAL_SUSTAINED", "APPEAL_DENIED")
BLOCKING_CASE_STATUSES = ("OPEN", "DETERMINED", "APPEALED")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return D(str(value))


def r1(value):
    return dec(value).quantize(D("0.1"), rounding=ROUND_HALF_UP)


def r2(value):
    return dec(value).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def money(value):
    return dec(value).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def pct(numerator, denominator):
    """round(numerator / denominator * 100, 2) with round-half-up."""
    denominator = dec(denominator)
    if denominator == 0:
        return r2(ZERO)
    return r2(dec(numerator) / denominator * D("100"))


def floor_int(value):
    return int(dec(value).to_integral_value(rounding="ROUND_FLOOR"))


def tier(points):
    if points >= SUSPENSION_THRESHOLD_POINTS:
        return "SUSPENDED"
    if points >= PROBATION_THRESHOLD_POINTS:
        return "ON_PROBATION"
    return "GOOD_STANDING"
