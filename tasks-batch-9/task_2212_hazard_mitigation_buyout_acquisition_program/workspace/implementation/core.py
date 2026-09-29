"""Core primitives: errors, response envelope, logical clock, date/rounding helpers."""
import calendar
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 422,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_BCA_NOT_FOUND": 404,
    "ERR_PARCEL_NOT_FOUND": 404,
    "ERR_APPRAISAL_NOT_FOUND": 404,
    "ERR_DOB_RECORD_NOT_FOUND": 404,
    "ERR_OFFER_NOT_FOUND": 404,
    "ERR_RELOCATION_CASE_NOT_FOUND": 404,
    "ERR_CLOSING_NOT_FOUND": 404,
    "ERR_CONTRACTOR_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_DISCONNECTION_NOT_FOUND": 404,
    "ERR_DEED_RESTRICTION_NOT_FOUND": 404,
    "ERR_LEDGER_ENTRY_NOT_FOUND": 404,
    "ERR_ADJACENCY_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_ADJACENCY_SELF_REFERENCE": 422,
    "ERR_PARCEL_PROJECT_MISMATCH": 422,
    "ERR_STALE_PARCEL_VERSION": 412,
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_INVALID_PROJECT_STATE": 409,
    "ERR_PROJECT_NOT_APPROVED": 409,
    "ERR_INVALID_BCA_STATE": 409,
    "ERR_INVALID_APPRAISAL_STATE": 409,
    "ERR_INVALID_OFFER_STATE": 409,
    "ERR_INVALID_CASE_STATE": 409,
    "ERR_INVALID_CLOSING_STATE": 409,
    "ERR_INVALID_WORK_ORDER_STATE": 409,
    "ERR_INVALID_DISCONNECTION_STATE": 409,
    "ERR_INVALID_RESTRICTION_STATE": 409,
    "ERR_INVALID_CONTRACTOR_STATE": 409,
    "ERR_ALREADY_REVERSED": 409,
    "ERR_ASBESTOS_SURVEY_MISSING": 422,
    "ERR_CONTRACTOR_SUSPENDED": 409,
    "ERR_DEMOLITION_REWORK_LIMIT": 409,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_APPRAISAL_WINDOW_OVERLAP": 409,
    "ERR_DEMOLITION_WINDOW_CONFLICT": 409,
    "ERR_OFFER_NOT_YET_EXPIRED": 409,
    "ERR_RELOCATION_PERIOD_OVERLAP": 409,
    "ERR_FUTURE_DATED_FINDING": 422,
    "ERR_MONITORING_OVERDUE": 409,
    "ERR_PERIOD_OF_PERFORMANCE_EXPIRED": 422,
    "ERR_BCR_BELOW_THRESHOLD": 422,
    "ERR_UTILITY_DISCONNECT_INCOMPLETE": 409,
    "ERR_NEIGHBORHOOD_NONVIABLE": 409,
    "ERR_PRE_EVENT_VALUE_NOT_DETERMINED": 422,
    "ERR_PARTICIPATION_NOT_VOLUNTARY": 409,
    "ERR_REVIEW_APPRAISAL_REQUIRED": 422,
    "ERR_DEBRIS_DIVERSION_BELOW_MINIMUM": 422,
    "ERR_DOB_EXCEEDS_BASE_VALUE": 422,
    "ERR_FEDERAL_SHARE_CAP_EXCEEDED": 422,
    "ERR_PROGRAM_INCOME_OVERDRAWN": 422,
    "ERR_PROGRAM_INCOME_OUTSTANDING": 409,
    "ERR_RELOCATION_NOT_SETTLED": 409,
    "ERR_TENANT_INELIGIBLE": 422,
    "ERR_DEMOLITION_NOT_COMPLETE": 409,
    "ERR_OPEN_SPACE_RESTRICTION_ACTIVE": 409,
    "ERR_VALUATION_BASIS_MISMATCH": 422,
    "ERR_APPRAISAL_REVISION_LIMIT": 409,
    "ERR_APPEAL_LIMIT_REACHED": 409,
    "ERR_TERMINATION_NOT_AUTHORIZED": 422,
    "ERR_PROHIBITED_USE_UNRESOLVED": 409,
    "ERR_DUPLICATE_PROJECT_CODE": 409,
    "ERR_DUPLICATE_APN": 409,
    "ERR_DUPLICATE_ADJACENCY": 409,
    "ERR_DUPLICATE_UTILITY_TYPE": 409,
    "ERR_DUPLICATE_HOUSEHOLD_REFERENCE": 409,
}

ERROR_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Missing or empty X-User-ID header.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted to invoke this operation.",
    "ERR_SEGREGATION_OF_DUTIES": "A segregation-of-duties bar collides with the acting user.",
    "ERR_INVALID_REQUEST": "The request body or query string failed structural validation.",
    "ERR_PROJECT_NOT_FOUND": "The mitigation project does not exist.",
    "ERR_BCA_NOT_FOUND": "The benefit-cost analysis does not exist.",
    "ERR_PARCEL_NOT_FOUND": "The parcel does not exist.",
    "ERR_APPRAISAL_NOT_FOUND": "The appraisal does not exist.",
    "ERR_DOB_RECORD_NOT_FOUND": "The duplication-of-benefits record does not exist.",
    "ERR_OFFER_NOT_FOUND": "The purchase offer does not exist.",
    "ERR_RELOCATION_CASE_NOT_FOUND": "The relocation case does not exist.",
    "ERR_CLOSING_NOT_FOUND": "The closing record does not exist.",
    "ERR_CONTRACTOR_NOT_FOUND": "The demolition contractor does not exist.",
    "ERR_WORK_ORDER_NOT_FOUND": "The demolition work order does not exist.",
    "ERR_DISCONNECTION_NOT_FOUND": "The utility disconnection does not exist.",
    "ERR_DEED_RESTRICTION_NOT_FOUND": "The deed restriction does not exist.",
    "ERR_LEDGER_ENTRY_NOT_FOUND": "The program income ledger entry does not exist.",
    "ERR_ADJACENCY_NOT_FOUND": "The parcel adjacency does not exist.",
    "ERR_INSPECTION_NOT_FOUND": "The monitoring inspection does not exist.",
    "ERR_ADJACENCY_SELF_REFERENCE": "An adjacency may not name the same parcel at both ends.",
    "ERR_PARCEL_PROJECT_MISMATCH": "A referenced entity does not belong to the expected parent.",
    "ERR_STALE_PARCEL_VERSION": "expected_parcel_version does not match the parcel's current version.",
    "ERR_STALE_PROJECT_VERSION": "expected_project_version does not match the project's current version.",
    "ERR_INVALID_PROJECT_STATE": "The mitigation project is not in a permitted state for this operation.",
    "ERR_PROJECT_NOT_APPROVED": "The mitigation project is not APPROVED.",
    "ERR_INVALID_BCA_STATE": "The benefit-cost analysis is not in a permitted state for this operation.",
    "ERR_INVALID_APPRAISAL_STATE": "The appraisal is not in a permitted state for this operation.",
    "ERR_INVALID_OFFER_STATE": "The purchase offer is not in a permitted state for this operation.",
    "ERR_INVALID_CASE_STATE": "The relocation case is not in a permitted state for this operation.",
    "ERR_INVALID_CLOSING_STATE": "The closing record is not in a permitted state for this operation.",
    "ERR_INVALID_WORK_ORDER_STATE": "The work order is not in a permitted state for this operation.",
    "ERR_INVALID_DISCONNECTION_STATE": "The disconnection's parent work order is not in a permitted state.",
    "ERR_INVALID_RESTRICTION_STATE": "The deed restriction is not in a permitted state for this operation.",
    "ERR_INVALID_CONTRACTOR_STATE": "The contractor already holds the requested status.",
    "ERR_ALREADY_REVERSED": "The record has already been reversed.",
    "ERR_ASBESTOS_SURVEY_MISSING": "The asbestos survey is missing, positive or abated without a certified contractor.",
    "ERR_CONTRACTOR_SUSPENDED": "The demolition contractor is suspended.",
    "ERR_DEMOLITION_REWORK_LIMIT": "The demolition rework limit has been exceeded.",
    "ERR_OFFER_EXPIRED": "The offer validity window has lapsed.",
    "ERR_APPRAISAL_WINDOW_OVERLAP": "The appraisal validity window overlaps another appraisal on this parcel.",
    "ERR_DEMOLITION_WINDOW_CONFLICT": "The contractor's buffered-window capacity is exhausted.",
    "ERR_OFFER_NOT_YET_EXPIRED": "The offer validity window has not yet lapsed.",
    "ERR_RELOCATION_PERIOD_OVERLAP": "The rental assistance period overlaps another case for this household.",
    "ERR_FUTURE_DATED_FINDING": "The supplied date is later than the current logical date.",
    "ERR_MONITORING_OVERDUE": "A deed restriction on this project is overdue for monitoring.",
    "ERR_PERIOD_OF_PERFORMANCE_EXPIRED": "The scheduled closing date falls outside the period of performance.",
    "ERR_BCR_BELOW_THRESHOLD": "The validated benefit-cost ratio is below the approval threshold.",
    "ERR_UTILITY_DISCONNECT_INCOMPLETE": "Not every required utility disconnection is confirmed.",
    "ERR_NEIGHBORHOOD_NONVIABLE": "The neighborhood viability status is NONVIABLE.",
    "ERR_PRE_EVENT_VALUE_NOT_DETERMINED": "The parcel's pre-event fair market value has not been determined.",
    "ERR_PARTICIPATION_NOT_VOLUNTARY": "The parcel's participation status does not permit this operation.",
    "ERR_REVIEW_APPRAISAL_REQUIRED": "A review appraisal in the required posture is missing.",
    "ERR_DEBRIS_DIVERSION_BELOW_MINIMUM": "The debris diversion percentage is below the minimum.",
    "ERR_DOB_EXCEEDS_BASE_VALUE": "The duplication-of-benefits total exceeds the appraised base value.",
    "ERR_FEDERAL_SHARE_CAP_EXCEEDED": "The federal share cap would be exceeded.",
    "ERR_PROGRAM_INCOME_OVERDRAWN": "The program income balance would go negative.",
    "ERR_PROGRAM_INCOME_OUTSTANDING": "The program income balance is not zero.",
    "ERR_RELOCATION_NOT_SETTLED": "A relocation case on this parcel is not yet settled.",
    "ERR_TENANT_INELIGIBLE": "A tenant displaced fewer than ninety days is statutorily ineligible.",
    "ERR_DEMOLITION_NOT_COMPLETE": "The parcel's structure has not been demolished.",
    "ERR_OPEN_SPACE_RESTRICTION_ACTIVE": "Title has already passed and the open-space encumbrance is active.",
    "ERR_VALUATION_BASIS_MISMATCH": "The offer basis does not correspond to the source appraisal's valuation basis.",
    "ERR_APPRAISAL_REVISION_LIMIT": "The appraisal revision limit has been reached.",
    "ERR_APPEAL_LIMIT_REACHED": "The relocation appeal limit has been reached.",
    "ERR_TERMINATION_NOT_AUTHORIZED": "The termination authorization reference is not a federal authorization.",
    "ERR_PROHIBITED_USE_UNRESOLVED": "A different prohibited use is still uncured on this restriction.",
    "ERR_DUPLICATE_PROJECT_CODE": "A mitigation project with this project_code already exists.",
    "ERR_DUPLICATE_APN": "A parcel with this apn already exists on the project.",
    "ERR_DUPLICATE_ADJACENCY": "An adjacency already links this unordered pair of parcels.",
    "ERR_DUPLICATE_UTILITY_TYPE": "A disconnection for this utility_type already exists on the work order.",
    "ERR_DUPLICATE_HOUSEHOLD_REFERENCE": "A relocation case with this household_reference already exists on the parcel.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.status = ERROR_STATUS.get(error_id, 422)
        self.message = message or ERROR_MESSAGE.get(error_id, error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

DEFAULT_LOGICAL_CLOCK_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
_CLOCK = {"now": DEFAULT_LOGICAL_CLOCK_UTC}


def clock_now():
    return _CLOCK["now"]


def clock_date():
    return _CLOCK["now"].astimezone(UTC).date()


def set_clock(dt):
    _CLOCK["now"] = dt.astimezone(UTC)


def reset_clock():
    _CLOCK["now"] = DEFAULT_LOGICAL_CLOCK_UTC


# --------------------------------------------------------------------------
# Identity / timestamps
# --------------------------------------------------------------------------

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_id():
    return str(uuid.uuid4())


def fmt_dt(dt):
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def wall_now_str():
    return fmt_dt(datetime.now(UTC))


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# --------------------------------------------------------------------------
# Date / datetime parsing
# --------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?(([Zz])|([+-]\d{2}:?\d{2}))?$"
)


def parse_date(value):
    """Strict YYYY-MM-DD -> datetime.date, or None when not parseable."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def parse_datetime(value):
    """ISO 8601 UTC instant -> aware datetime, or None when not parseable."""
    if not isinstance(value, str) or not _DT_RE.match(value):
        return None
    txt = value.strip().replace(" ", "T").replace("t", "T")
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_date(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def add_months(d, months):
    """Add whole calendar months, clamping to the last day of the target month."""
    total = (d.year * 12 + (d.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last))


def add_days(d, days):
    return d + timedelta(days=days)


# --------------------------------------------------------------------------
# Rounding
# --------------------------------------------------------------------------

def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    """Round half up on the positive magnitude, then re-attach the sign."""
    value = D(value)
    q = Decimal(1).scaleb(-places)
    mag = (-value if value < 0 else value).quantize(q, rounding=ROUND_HALF_UP)
    return -mag if value < 0 else mag


def rhu_int(value):
    return int(rhu(value, 0))


def q(value, places):
    """Force a Decimal to a fixed number of decimal places for stored precision."""
    return rhu(value, places)
