"""Shared primitives: decimal helpers, timestamp handling, logical clock, id minting."""
import random
import string
import uuid
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

API_PREFIX = "/draft-service"

# ---------------------------------------------------------------- decimal utils

def D(value):
    """Coerce anything numeric into an exact Decimal (never via binary float)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimal places."""
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    """Round half up to a whole number, returned as int."""
    return int(D(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def ceil_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def jnum(value):
    """Render a Decimal for JSON output."""
    if value is None:
        return None
    return float(value)


# ------------------------------------------------------------------- timestamps

def now_iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits and a Z suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(text):
    """Parse an ISO 8601 UTC timestamp. Returns None when unparseable."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(text):
    """Parse a YYYY-MM-DD calendar date. Returns None when unparseable."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if len(raw) != 10:
        return None
    try:
        return date(int(raw[0:4]), int(raw[5:7]), int(raw[8:10])) if raw[4] == "-" and raw[7] == "-" else None
    except (ValueError, TypeError):
        return None


def date_str(d):
    return d.isoformat() if d is not None else None


def whole_days_between(later, earlier):
    """floor((later - earlier) / 86400) as an int; negative when later < earlier."""
    delta = later - earlier
    return floor_int(D(delta.total_seconds()) / D(86400))


def hours_between(later, earlier):
    return D((later - earlier).total_seconds()) / D(3600)


def add_days(dt, days):
    return dt + timedelta(days=int(days))


# -------------------------------------------------------------------- id / meta

def new_id():
    return str(uuid.uuid4())


_REQ_ALPHABET = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_REQ_ALPHABET) for _ in range(20))


# --------------------------------------------------------------- roles / consts

ROLE_DISPATCH = "DispatchCoordinator"
ROLE_TECH = "ServiceTechnician"
ROLE_VENUE = "VenueManager"
ROLE_AUDITOR = "QualityAuditor"
ROLE_BREWER = "BrewerRep"
ALL_ROLES = [ROLE_DISPATCH, ROLE_TECH, ROLE_VENUE, ROLE_AUDITOR, ROLE_BREWER]

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
PAGE_OFFSET_MIN = 0

# ---- calculation constants (calculations.chemical_cycle_dosing)
VOLUME_L_PER_FOOT = {Decimal("0.1875"): D("0.0173"), Decimal("0.25"): D("0.0308"),
                     Decimal("0.375"): D("0.0692")}
FLUSH_FACTOR = D("3.0")
MIN_SOLUTION_LITERS = 4
TARGET_ACTIVE_PCT = {"CAUSTIC": D("2.0"), "ACID": D("1.0")}
MIN_EFFECTIVE_PCT = {"CAUSTIC": D("1.5"), "ACID": D("0.75")}
MIN_TEMP_F = {"CAUSTIC": D("95.0"), "ACID": D("70.0")}
MIN_USABLE_LITERS = D("0.05")

# ---- calculation constants (calculations.gas_balance_target)
CO2_BASE_VOLUMES = D("1.2")
VOL_TO_PSI = D("5.5")
TEMP_REF_F = D("38.0")
TEMP_PSI_SLOPE = D("0.45")
RISE_PSI_PER_FOOT = D("0.5")
FAUCET_LOSS_PSI = D("2.0")
BALANCE_TOLERANCE_PSI = D("0.75")
APPLIED_PSI_TOLERANCE = D("0.5")
CO2_PCT_TOLERANCE = D("2.0")
RESTRICTION_PSI_PER_FOOT = {Decimal("0.1875"): D("2.2"), Decimal("0.25"): D("0.85"),
                            Decimal("0.375"): D("0.30")}
TARGET_CO2_VOLUMES = {
    "ALE": {"COLD": D("2.4"), "MILD": D("2.5"), "WARM": D("2.6")},
    "LAGER": {"COLD": D("2.6"), "MILD": D("2.7"), "WARM": D("2.8")},
    "CIDER": {"COLD": D("2.8"), "MILD": D("2.9"), "WARM": D("3.0")},
}
NITRO_TARGET_VOLUMES = D("1.2")
NITRO_REQUIRED_CO2_PCT = D("25.0")
CO2_PCT_FLOOR = D("40.0")
CO2_PCT_CEILING = D("100.0")
BAND_COLD_MAX_F = D("38.0")
BAND_MILD_MAX_F = D("42.0")

# ---- calculation constants (calculations.visit_charge_settlement)
WAIVER_WITHHOLD_BPS = 1000
FREQUENCY_MULTIPLIER = {14: D("1.00"), 21: D("1.10"), 28: D("1.25")}
ALLOWED_FREQUENCY_DAYS = [14, 21, 28]

# ---- calculation constants (calculations.yield_loss_estimate)
SEVERITY_FACTOR = {"FOAMY_POUR": D("0.35"), "FLAT_POUR": D("0.20"), "OFF_FLAVOR": D("0.50"),
                   "SLOW_POUR": D("0.15"), "CLOUDY": D("0.30")}
MAX_DAYS_AT_RISK = 30
WHOLESALE_CENTS_PER_LITER = D("480")
FOAM_ALLOWANCE_LITERS_PER_DAY = D("0.5")

# ---- calculation constants (calculations.brewer_funding_waterfall)
FUNDED_SCOPE_BUCKETS = {
    "CLEANING_ONLY": ["CLEANING"],
    "CLEANING_AND_PARTS": ["CLEANING", "PARTS"],
    "FULL": ["CLEANING", "PARTS", "BASE_FEE"],
}
BUCKET_ORDER = ["CLEANING", "PARTS", "BASE_FEE"]

# ---- calculation constants (calculations.glycol_health_score)
READING_WINDOW = 3
TARGET_COOLER_TEMP_F = D("38.0")
TEMP_PENALTY_PER_DEGREE = D("8.0")
MIN_GLYCOL_PCT = D("30.0")
GLYCOL_PENALTY_PER_PCT = D("2.5")
MIN_PUMP_PSI = D("9.0")
PUMP_PENALTY_FLAT = D("12.0")
GLYCOL_SERVICE_INTERVAL_DAYS = 180
SERVICE_PENALTY_PER_DAY = D("0.6")
WATCH_THRESHOLD = D("75.0")
ALARM_THRESHOLD = D("50.0")

# ---- calculation constants (calculations.line_compliance_projection)
GRACE_DAYS = 3
MAX_LEAD_DAYS = 45
EARLY_WINDOW_DAYS = 2
TRAVEL_BUFFER_MINUTES = 30
DISPUTE_WINDOW_HOURS = 168
WAIVER_WAIT_HOURS = 72
REOPEN_WINDOW_HOURS = 336
REOPEN_LIMIT = 2
MAX_DIAGNOSTIC_ROUNDS = 3
