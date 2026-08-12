"""Constants, parsing helpers, and Decimal arithmetic utilities."""
from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError, ERR_INVALID_REQUEST

# ---- Calculation constants (SCAFFOLD 1.3) ----
GRADE_SCALE = {
    "A": Decimal("4.0"), "A-": Decimal("3.7"), "B+": Decimal("3.3"),
    "B": Decimal("3.0"), "B-": Decimal("2.7"), "C+": Decimal("2.3"),
    "C": Decimal("2.0"), "C-": Decimal("1.7"), "D": Decimal("1.0"),
    "F": Decimal("0.0"),
}
TRANSFER_MIN_GRADE_POINTS = Decimal("2.0")
PROVISIONAL_FACTOR = {"QUARTER": Decimal("0.75"), "SEMESTER": Decimal("1.0")}
MAX_TRANSFER_CREDITS = Decimal("60.0")
SLOT_NEED = {
    "MAJOR_CORE": Decimal("30.0"),
    "MAJOR_ELECTIVE": Decimal("12.0"),
    "GENED_COMMS": Decimal("6.0"),
    "GENED_MATH": Decimal("6.0"),
    "GENED_SCIENCE": Decimal("6.0"),
    "GENED_HUMANITIES": Decimal("6.0"),
    "GENED_SOCIAL": Decimal("6.0"),
    "FREE_ELECTIVE": Decimal("24.0"),
}
SLOT_ORDER = [
    "MAJOR_CORE", "MAJOR_ELECTIVE", "GENED_COMMS", "GENED_MATH",
    "GENED_SCIENCE", "GENED_HUMANITIES", "GENED_SOCIAL", "FREE_ELECTIVE",
]
RESIDENCY_MIN_INSTITUTIONAL_CREDITS = Decimal("30.0")
MAX_PLA_CREDITS = Decimal("30.0")
APPEAL_WINDOW_DAYS = 30

ROLES = ["RegistrarAdmin", "TransferCenterStaff", "TransferEvaluator",
         "FacultyAdjudicator", "Student"]

CREDIT_SYSTEMS = {"SEMESTER", "QUARTER"}
COURSE_LEVELS = {"LOWER", "UPPER", "GRADUATE"}
GENED_TAGS = {"GENED_COMMS", "GENED_MATH", "GENED_SCIENCE",
              "GENED_HUMANITIES", "GENED_SOCIAL"}
EQUIVALENCY_TYPES = {"DIRECT", "GENED_ONLY", "ELECTIVE"}
PLA_SOURCE_TYPES = {"MILITARY_JST", "CLEP", "AP", "IB", "PORTFOLIO"}
AGREEMENT_STATUSES = {"DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED", "SUPERSEDED"}


def rhu(value, places):
    """Round half-up to the given number of decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def parse_dt(s):
    """Parse an ISO 8601 date or datetime string to an aware UTC datetime."""
    if isinstance(s, datetime):
        d = s
    elif isinstance(s, str):
        t = s.strip()
        if t.endswith(("Z", "z")):
            t = t[:-1] + "+00:00"
        try:
            d = datetime.fromisoformat(t)
        except ValueError:
            d = datetime.combine(date.fromisoformat(t), datetime.min.time())
    else:
        raise ValueError("not a datetime")
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def fmt_dt(d):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    d = d.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def to_decimal(v):
    """Convert a JSON number to Decimal (rejecting bools/non-numerics)."""
    if isinstance(v, bool):
        raise ValueError("bool is not a number")
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    raise ValueError("not a number")


def is_half_step(d):
    """True when d is an exact multiple of 0.5."""
    doubled = d * 2
    return doubled == doubled.to_integral_value()


# ---- Request-body validation helpers (all raise ERR_INVALID_REQUEST) ----

def req_present(body, field):
    v = body.get(field)
    if v is None or (isinstance(v, str) and v.strip() == ""):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Missing required field: {field}")
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} must be a string")
    return v


def req_str(body, field):
    v = req_present(body, field)
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} must be a string")
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Field {field} must be one of {sorted(allowed)}")
    return v


def req_number(body, field):
    v = req_present(body, field)
    try:
        return to_decimal(v)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Field {field} must be a number")


def req_int(body, field):
    v = req_present(body, field)
    if isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} must be an integer")
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} must be an integer")


def req_date(body, field):
    v = req_present(body, field)
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} must be an ISO date")
    try:
        parse_dt(v)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Field {field} must be a valid ISO 8601 date/datetime")
    return v


def min_len(value, field, n):
    if len(value) < n:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Field {field} must be at least {n} characters")
    return value
