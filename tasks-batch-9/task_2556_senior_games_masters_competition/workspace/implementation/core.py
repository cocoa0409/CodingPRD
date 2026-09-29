"""Foundation: clock, ids, timestamps, response envelope, errors, auth, validation."""
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from flask import jsonify, request

UTC = timezone.utc

# ---------------------------------------------------------------- roles / auth
ROLE_GAMES_ADMIN = "GamesAdmin"
ROLE_REGISTRATION_OFFICER = "RegistrationOfficer"
ROLE_ATHLETE = "Athlete"
ROLE_MEDICAL_DIRECTOR = "MedicalDirector"
ROLE_SPORT_OFFICIAL = "SportOfficial"
ROLE_RECORDS_RATIFIER = "RecordsRatifier"
ROLE_SPONSOR_LIAISON = "SponsorLiaison"

ALL_ROLES = (
    ROLE_GAMES_ADMIN,
    ROLE_REGISTRATION_OFFICER,
    ROLE_ATHLETE,
    ROLE_MEDICAL_DIRECTOR,
    ROLE_SPORT_OFFICIAL,
    ROLE_RECORDS_RATIFIER,
    ROLE_SPONSOR_LIAISON,
)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").lower().capitalize()


# ------------------------------------------------------------------- ids/clock
def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


class LogicalClock:
    """Server-held logical clock. The host wall clock is never consulted."""

    def __init__(self):
        self.current = parse_datetime(DEFAULT_CLOCK_ISO)

    def now(self):
        return self.current

    def set(self, moment):
        self.current = moment

    def iso(self):
        return iso_ms(self.current)


def iso_ms(moment):
    """ISO 8601 UTC with exactly three fractional-second digits and a Z suffix."""
    if moment is None:
        return None
    moment = moment.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year,
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second,
        moment.microsecond // 1000,
    )


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_datetime(value):
    """Parse an ISO 8601 instant. Returns a tz-aware UTC datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def as_date(value):
    """Calendar date of a stored date string."""
    return parse_date(value)


def as_dt(value):
    return parse_datetime(value)


# ------------------------------------------------------------------- rounding
def round_half_up(value, places=0):
    """Decimal ROUND_HALF_UP. Accepts Decimal, Fraction, int."""
    if isinstance(value, Fraction):
        value = Decimal(value.numerator) / Decimal(value.denominator)
    elif not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def cents(value):
    return int(round_half_up(value, 0))


# ------------------------------------------------------------------- envelope
def _meta(clock):
    return {"api_request_id": new_request_id(), "api_request_timestamp": clock.iso()}


def ok_object(clock, payload, status=200):
    body = {"meta": _meta(clock), "response_type": "object", "data": payload}
    return jsonify(body), status


def ok_list(clock, items, limit, offset, total_count):
    meta = _meta(clock)
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(clock, error_id, message):
    return {
        "meta": _meta(clock),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# -------------------------------------------------------------- error catalog
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_GAMES_EDITION_NOT_FOUND": 404,
    "ERR_SPORT_NOT_FOUND": 404,
    "ERR_SPORT_EVENT_NOT_FOUND": 404,
    "ERR_VENUE_NOT_FOUND": 404,
    "ERR_SESSION_SLOT_NOT_FOUND": 404,
    "ERR_ATHLETE_NOT_FOUND": 404,
    "ERR_QUALIFYING_RESULT_NOT_FOUND": 404,
    "ERR_SPORT_ENTRY_NOT_FOUND": 404,
    "ERR_MEDICAL_SCREENING_NOT_FOUND": 404,
    "ERR_PERSONNEL_NOT_FOUND": 404,
    "ERR_PERSONNEL_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_COMPETITION_RESULT_NOT_FOUND": 404,
    "ERR_AGE_GROUP_RECORD_NOT_FOUND": 404,
    "ERR_ACCOMMODATION_BLOCK_NOT_FOUND": 404,
    "ERR_VILLAGE_STAY_NOT_FOUND": 404,
    "ERR_SPONSORSHIP_COMMITMENT_NOT_FOUND": 404,
    "ERR_STALE_SPORT_EVENT_VERSION": 412,
    "ERR_STALE_BLOCK_VERSION": 412,
    "ERR_STALE_GAMES_EDITION_VERSION": 412,
    "ERR_EDITION_STATE_INVALID": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_ATHLETE_NOT_REGISTERED": 409,
    "ERR_VENUE_CLOSED": 409,
    "ERR_RESULT_NOT_RECORD_ELIGIBLE": 409,
    "ERR_SLOT_NOT_COMPETED": 409,
    "ERR_ATHLETE_MEDICAL_HOLD": 422,
    "ERR_MEDICAL_COVERAGE_REQUIRED": 422,
    "ERR_EMERGENCY_PROTOCOL_INSUFFICIENT": 422,
    "ERR_QUALIFYING_RESULT_INVALID": 422,
    "ERR_AGE_GROUP_MISMATCH": 422,
    "ERR_CERTIFICATION_INSUFFICIENT": 422,
    "ERR_ATHLETE_UNDER_MINIMUM_AGE": 422,
    "ERR_PERSONNEL_DOUBLE_BOOKED": 409,
    "ERR_ATHLETE_SCHEDULE_CONFLICT": 409,
    "ERR_REGISTRATION_DEADLINE_PASSED": 422,
    "ERR_STAY_OUTSIDE_VILLAGE_WINDOW": 422,
    "ERR_VENUE_AREA_CAPACITY_EXCEEDED": 409,
    "ERR_BLOCK_NIGHT_FULL": 409,
    "ERR_EVENT_CAPACITY_FULL": 409,
    "ERR_PERSONNEL_DAILY_LIMIT_EXCEEDED": 422,
    "ERR_REVISION_LIMIT_REACHED": 422,
    "ERR_PROTEST_LIMIT_REACHED": 422,
    "ERR_NO_ELIGIBLE_ENTRIES": 422,
    "ERR_MIN_ENTRIES_NOT_MET": 422,
    "ERR_SPORT_CODE_TAKEN": 409,
    "ERR_ATHLETE_EMAIL_TAKEN": 409,
    "ERR_ASSIGNMENT_DUPLICATE": 409,
    "ERR_RESULT_ALREADY_RECORDED": 409,
    "ERR_DUPLICATE_ENTRY": 409,
    "ERR_FEE_AMOUNT_MISMATCH": 422,
    "ERR_IMPACT_ALREADY_FINALIZED": 409,
}


def fail(error_id, message=None):
    raise ApiError(error_id, ERROR_STATUS.get(error_id, 400), message)


def bad_request(message=None):
    fail("ERR_INVALID_REQUEST", message)


# --------------------------------------------------------------- auth helpers
def authenticate(*allowed_roles):
    """Priority 1-3: headers present, role known, role permitted."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    role = role.strip()
    user_id = str(user_id).strip()
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "Unknown role")
    if allowed_roles and role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED", "Role %s may not perform this operation" % role)
    return user_id, role


def read_only():
    """Every read endpoint is open to all seven authenticated roles."""
    return authenticate(*ALL_ROLES)


# ---------------------------------------------------------------- pagination
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _paging_int(raw, default, minimum, maximum):
    if raw is None:
        return default
    text = str(raw).strip()
    if text == "":
        fail("ERR_INVALID_PAGINATION")
    if not re.match(r"^[+-]?\d+$", text):
        fail("ERR_INVALID_PAGINATION")
    value = int(text)
    if value < minimum:
        fail("ERR_INVALID_PAGINATION")
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_PAGINATION")
    return value


def pagination():
    limit = _paging_int(
        request.args.get("limit"),
        PAGINATION_DEFAULT_LIMIT,
        PAGINATION_MIN_LIMIT,
        PAGINATION_MAX_LIMIT,
    )
    offset = _paging_int(
        request.args.get("offset"), PAGINATION_DEFAULT_OFFSET, 0, None
    )
    return limit, offset


# --------------------------------------------------------- body field parsing
MISSING = object()
FREE_TEXT = True


class Field:
    def __init__(
        self,
        name,
        kind,
        required=True,
        default=MISSING,
        enum=None,
        minimum=None,
        maximum=None,
        regex=None,
        nullable=False,
        allow_empty=False,
        exclusive_min=None,
    ):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.enum = enum
        self.minimum = minimum
        self.maximum = maximum
        self.regex = regex
        self.nullable = nullable
        self.allow_empty = allow_empty
        self.exclusive_min = exclusive_min


def raw_body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        bad_request("Request body must be valid JSON")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad_request("Request body must be a JSON object")
    return payload


def parse_body(fields):
    """Priority 4: presence, type, range, enum and unknown-field rejection."""
    payload = raw_body()
    known = {f.name for f in fields}
    for key in payload:
        if key not in known:
            bad_request("Unknown field: %s" % key)
    out = {}
    for spec in fields:
        if spec.name not in payload:
            if spec.required:
                bad_request("Missing required field: %s" % spec.name)
            out[spec.name] = None if spec.default is MISSING else spec.default
            continue
        out[spec.name] = _coerce(spec, payload[spec.name])
    return out


def _coerce(spec, value):
    if value is None:
        if spec.nullable or (not spec.required and spec.default is None):
            return None
        bad_request("Field %s may not be null" % spec.name)
    kind = spec.kind
    if kind in ("str", "id", "date", "datetime"):
        if not isinstance(value, str):
            bad_request("Field %s must be a string" % spec.name)
        if not spec.allow_empty and value.strip() == "":
            bad_request("Field %s must not be empty" % spec.name)
        if kind == "date" and parse_date(value) is None:
            bad_request("Field %s must be an ISO 8601 date" % spec.name)
        if kind == "datetime" and parse_datetime(value) is None:
            bad_request("Field %s must be an ISO 8601 timestamp" % spec.name)
    elif kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            bad_request("Field %s must be an integer" % spec.name)
    elif kind == "num":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            bad_request("Field %s must be a number" % spec.name)
    elif kind == "bool":
        if not isinstance(value, bool):
            bad_request("Field %s must be a boolean" % spec.name)
    elif kind == "obj":
        if not isinstance(value, dict):
            bad_request("Field %s must be an object" % spec.name)
    elif kind == "arr_str":
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            bad_request("Field %s must be an array of strings" % spec.name)
    if spec.enum is not None and value not in spec.enum:
        bad_request("Field %s must be one of %s" % (spec.name, ", ".join(spec.enum)))
    if spec.regex is not None and not re.match(spec.regex, value):
        bad_request("Field %s has an invalid format" % spec.name)
    if spec.minimum is not None and value < spec.minimum:
        bad_request("Field %s must be >= %s" % (spec.name, spec.minimum))
    if spec.exclusive_min is not None and value <= spec.exclusive_min:
        bad_request("Field %s must be > %s" % (spec.name, spec.exclusive_min))
    if spec.maximum is not None and value > spec.maximum:
        bad_request("Field %s must be <= %s" % (spec.name, spec.maximum))
    return value


def no_body():
    """Endpoints with no declared input still reject unknown fields."""
    parse_body([])
