"""Core infrastructure: logical clock, in-memory store, response envelope,
errors, auth, pagination and shape validation helpers.

Every structural name here is taken from PRD.md sections 2.1-2.9 and the
SCAFFOLD.yaml response_envelope / validations / errors tables.
"""
import random
import re
import string
import uuid
from calendar import monthrange
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------
ROLE_OWNER = "OwnerAgent"
ROLE_CA = "ContractAdministrator"
ROLE_HFO = "HudFieldOffice"
ROLE_PHA = "PhaAdministrator"
ROLES = (ROLE_OWNER, ROLE_CA, ROLE_HFO, ROLE_PHA)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# --------------------------------------------------------------------------
# Error catalogue (PRD section 5)
# --------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_PROPERTY_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_UA_CHANGE_REQUIRES_FIELD_OFFICE": 403,
    "ERR_OWNER_NOT_FOUND": 404,
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_RENEWAL_CASE_NOT_FOUND": 404,
    "ERR_STUDY_NOT_FOUND": 404,
    "ERR_COMPARABLE_NOT_FOUND": 404,
    "ERR_UA_ANALYSIS_NOT_FOUND": 404,
    "ERR_TENANT_NOT_FOUND": 404,
    "ERR_CERTIFICATION_NOT_FOUND": 404,
    "ERR_NOTICE_NOT_FOUND": 404,
    "ERR_DETERMINATION_NOT_FOUND": 404,
    "ERR_ENHANCED_VOUCHER_NOT_FOUND": 404,
    "ERR_VOUCHER_SUBMISSION_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_DUPLICATE_TIN": 409,
    "ERR_DUPLICATE_UNIT_NUMBER": 409,
    "ERR_STALE_TENANT_VERSION": 412,
    "ERR_STALE_CONTRACT_VERSION": 412,
    "ERR_STALE_PROPERTY_VERSION": 412,
    "ERR_TRANSITION_NOT_ALLOWED": 409,
    "ERR_OPEN_RENEWAL_CASE_EXISTS": 409,
    "ERR_MAX_CHALLENGE_ROUNDS": 409,
    "ERR_UA_ANALYSIS_IN_FLIGHT": 409,
    "ERR_DUPLICATE_VOUCHER_PERIOD": 409,
    "ERR_RCS_NOT_ACCEPTED": 409,
    "ERR_COVERING_VOUCHER_NOT_PAID": 409,
    "ERR_CLAIM_PAID_BLOCKS_REVERSAL": 409,
    "ERR_ENHANCED_VOUCHER_ISSUED_BLOCKS_RESCIND": 409,
    "ERR_OPTION_NOT_PERMITTED_FOR_TYPE": 422,
    "ERR_ADJUSTMENT_METHOD_CONFLICT": 422,
    "ERR_MUTM_OPTION_MISMATCH": 422,
    "ERR_OUTSIDE_RENEWAL_WINDOW": 422,
    "ERR_NOTICE_WINDOW_NOT_MET": 422,
    "ERR_OPT_OUT_NOTICE_PERIOD_INCOMPLETE": 422,
    "ERR_UA_INTERVAL_OVERLAP": 409,
    "ERR_CERT_INTERVAL_CONFLICT": 409,
    "ERR_PERIOD_NOT_ELAPSED": 422,
    "ERR_OPT_OUT_NOTICE_MISSING": 422,
    "ERR_NO_ELIGIBLE_COMPARABLES": 422,
    "ERR_TENANT_VOUCHER_UNRESOLVED": 422,
    "ERR_VACANCY_DAYS_CAP_EXCEEDED": 422,
    "ERR_RENT_EXCEEDS_COMPARABLE": 422,
    "ERR_BUDGET_RENT_EXCEEDS_CAP": 422,
    "ERR_NO_ENHANCEMENT_ENTITLEMENT": 422,
    "ERR_ZERO_VOUCHER_REQUEST": 422,
    "ERR_ZERO_CLAIM_AMOUNT": 422,
    "ERR_HAP_BUDGET_EXCEEDED": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# Logical clock (PRD 2.4) -- starts at 2026-08-01T00:00:00Z on every boot
# --------------------------------------------------------------------------
CLOCK_ORIGIN = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class _Clock:
    def __init__(self):
        self.value = CLOCK_ORIGIN

    def reset(self):
        self.value = CLOCK_ORIGIN


CLOCK = _Clock()


def now_dt():
    return CLOCK.value


def clock_date():
    return CLOCK.value.date()


def iso_ms(dt=None):
    dt = dt or CLOCK.value
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def clock_date_str():
    return clock_date().isoformat()


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def parse_instant(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_month(value):
    if not isinstance(value, str) or not MONTH_RE.match(value):
        return None
    year, month = int(value[0:4]), int(value[5:7])
    if month < 1 or month > 12:
        return None
    return year, month


def days_in_month(year, month):
    return monthrange(year, month)[1]


def month_first_day(year, month):
    return date(year, month, 1)


def month_last_day(year, month):
    return date(year, month, days_in_month(year, month))


def add_months(base, months):
    """Advance the month component, keeping the day-of-month (PRD 2.4)."""
    total = (base.year * 12 + (base.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(base.day, days_in_month(year, month))
    return date(year, month, day)


def days_between(start, end):
    """Half-open whole calendar days: start day excluded, end day counted."""
    return (end - start).days


# --------------------------------------------------------------------------
# Rounding discipline (PRD 2.7) -- integer cents, ROUND_HALF_UP
# --------------------------------------------------------------------------
def rhu(value):
    """Round half up (away from zero) to whole cents -> int."""
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_dollars(cents):
    """Round half up to the nearest whole dollar (multiple of 100 cents)."""
    value = Decimal(cents) / Decimal(100)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * 100


def rhu_4dp(value):
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def dec(value):
    return Decimal(str(value))


# --------------------------------------------------------------------------
# In-memory store -- empty on every boot, no seeding anywhere
# --------------------------------------------------------------------------
TABLES = (
    "owners", "properties", "contracts", "cases", "studies", "comparables",
    "analyses", "households", "certifications", "notices", "determinations",
    "vouchers", "submissions", "claims",
)


class _Store:
    def __init__(self):
        self.tables = {name: {} for name in TABLES}
        self.seq = 0

    def reset(self):
        for name in TABLES:
            self.tables[name] = {}
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


DB = _Store()


def table(name):
    return DB.tables[name]


def create(name, fields):
    stamp = iso_ms()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": DB.next_seq(),
    }
    row.update(fields)
    DB.tables[name][row["id"]] = row
    return row


def touch(row):
    row["version"] = row["version"] + 1
    row["updated_at"] = iso_ms()
    return row


def rows(name):
    return list(DB.tables[name].values())


def by_seq(items):
    return sorted(items, key=lambda r: r["_seq"])


def public(row):
    if isinstance(row, list):
        return [public(item) for item in row]
    if not isinstance(row, dict):
        return row
    return {k: v for k, v in row.items() if not k.startswith("_")}


# --------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_ms(),
    }


def respond_object(data, status=200):
    payload = {
        "meta": base_meta(),
        "response_type": "object",
        "data": public(data) if data is not None else {},
    }
    return jsonify(payload), status


def respond_array(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    payload = {
        "meta": meta,
        "response_type": "array",
        "data": [public(item) for item in items],
    }
    return jsonify(payload), 200


def respond_error(error_id, message, status):
    payload = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(payload), status


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total


# --------------------------------------------------------------------------
# Ladder step 1: authentication (PRD 2.1 / 2.9.1)
# --------------------------------------------------------------------------
def authenticate():
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role must be one of the four declared roles.")
    g.user_id = str(user_id)
    g.role = role


# --------------------------------------------------------------------------
# Ladder step 2: role permission (PRD 2.9.2)
# --------------------------------------------------------------------------
def require_roles(*allowed):
    if g.role not in allowed:
        fail("ERR_UNAUTHORIZED", "Role %s is not authorized for this endpoint." % g.role)


# --------------------------------------------------------------------------
# Ladder step 3: owner ownership (PRD 2.9.3)
# --------------------------------------------------------------------------
def require_owner(owner_id):
    if g.role == ROLE_OWNER and g.user_id != owner_id:
        fail("ERR_NOT_PROPERTY_OWNER", "Acting owner-agent does not own the target resource.")


# --------------------------------------------------------------------------
# Body handling and ladder step 6: request shape (PRD 2.9.6)
# --------------------------------------------------------------------------
def json_body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None or not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def bad_request(message):
    fail("ERR_INVALID_REQUEST", message)


def is_int(value):
    return type(value) is int


def is_num(value):
    return type(value) is int or type(value) is float


def need_str(body, name):
    value = body.get(name)
    if not isinstance(value, str) or not value.strip():
        bad_request("Field '%s' must be a non-empty string." % name)
    return value


def opt_str(body, name, default=None):
    if name not in body or body.get(name) is None:
        return default
    value = body.get(name)
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % name)
    return value


def need_int(body, name, minimum=None, maximum=None):
    value = body.get(name)
    if not is_int(value):
        bad_request("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad_request("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad_request("Field '%s' must be <= %s." % (name, maximum))
    return value


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if name not in body or body.get(name) is None:
        return default
    return need_int(body, name, minimum, maximum)


def need_enum(body, name, allowed):
    value = body.get(name)
    if not isinstance(value, str) or value not in allowed:
        bad_request("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if name not in body or body.get(name) is None:
        return default
    return need_enum(body, name, allowed)


def need_bool(body, name, default=None):
    if name not in body or body.get(name) is None:
        return default
    value = body.get(name)
    if type(value) is not bool:
        bad_request("Field '%s' must be a boolean." % name)
    return value


def need_date(body, name):
    value = body.get(name)
    parsed = parse_date(value)
    if parsed is None:
        bad_request("Field '%s' must be an ISO date in YYYY-MM-DD form." % name)
    return value


def opt_date(body, name, default=None):
    if name not in body or body.get(name) is None:
        return default
    return need_date(body, name)


def need_month(body, name):
    value = body.get(name)
    if parse_month(value) is None:
        bad_request("Field '%s' must be a billing month in YYYY-MM form." % name)
    return value


def need_number(body, name, minimum=None, maximum=None):
    value = body.get(name)
    if not is_num(value) or type(value) is bool:
        bad_request("Field '%s' must be a number." % name)
    if minimum is not None and dec(value) < dec(minimum):
        bad_request("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and dec(value) > dec(maximum):
        bad_request("Field '%s' must be <= %s." % (name, maximum))
    return value


def need_id_list(body, name):
    value = body.get(name)
    if not isinstance(value, list):
        bad_request("Field '%s' must be an array of identifiers." % name)
    for item in value:
        if not isinstance(item, str) or not item.strip():
            bad_request("Field '%s' must contain only identifier strings." % name)
    return value


# --------------------------------------------------------------------------
# Ladder step 7: pagination bounds (PRD 2.3 / 2.9.7)
# --------------------------------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _page_int(raw):
    if not isinstance(raw, str):
        fail("ERR_INVALID_PAGINATION", "Pagination parameters must be integers.")
    text = raw.strip()
    if not re.match(r"^[+-]?\d+$", text):
        fail("ERR_INVALID_PAGINATION", "Pagination parameters must be integers.")
    return int(text)


def read_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGE_LIMIT_DEFAULT if raw_limit is None else _page_int(raw_limit)
    offset = PAGE_OFFSET_DEFAULT if raw_offset is None else _page_int(raw_offset)
    if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
        fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    if offset < 0:
        fail("ERR_INVALID_PAGINATION", "offset must be at least 0.")
    return limit, offset


def filter_arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value
