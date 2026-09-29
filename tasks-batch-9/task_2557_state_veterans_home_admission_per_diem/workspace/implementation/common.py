"""Errors, response envelope, authentication/authorisation and request-shape
validation helpers shared by every blueprint."""
import random
import string
from decimal import Decimal

from flask import jsonify, request

from store import DATE_RE, MONTH_RE, now_iso, parse_date, parse_iso_datetime

ROLES = (
    "StateProgramAdmin",
    "AdmissionsCoordinator",
    "ClinicalAssessor",
    "BusinessOfficeManager",
    "FederalPerDiemAuditor",
    "SurveyAgency",
    "ResidentRepresentative",
)

# The full error catalogue of PRD section 5, error id -> HTTP status.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 422,
    "ERR_HOME_NOT_FOUND": 404,
    "ERR_CARE_UNIT_NOT_FOUND": 404,
    "ERR_APPLICANT_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_RESIDENT_NOT_FOUND": 404,
    "ERR_INCOME_RECORD_NOT_FOUND": 404,
    "ERR_CARE_PLAN_NOT_FOUND": 404,
    "ERR_CENSUS_DAY_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_TRANSACTION_NOT_FOUND": 404,
    "ERR_CARE_UNIT_VERSION_STALE": 412,
    "ERR_RESIDENT_VERSION_STALE": 412,
    "ERR_CLAIM_VERSION_STALE": 412,
    "ERR_APPLICANT_STATE_INVALID": 409,
    "ERR_REDETERMINATION_LIMIT": 409,
    "ERR_ASSESSMENT_STATE_INVALID": 409,
    "ERR_RESIDENT_STATE_INVALID": 409,
    "ERR_CARE_PLAN_STATE_INVALID": 409,
    "ERR_INCOME_RECORD_STATE_INVALID": 409,
    "ERR_CLAIM_STATE_INVALID": 409,
    "ERR_TRANSACTION_ALREADY_REVERSED": 409,
    "ERR_HOME_RECOGNITION_STATE_INVALID": 409,
    "ERR_HOME_NOT_RECOGNIZED": 409,
    "ERR_UNIT_NOT_CERTIFIED": 409,
    "ERR_UNIT_POSTURE_BLOCKED": 409,
    "ERR_CARE_LEVEL_MISMATCH": 409,
    "ERR_NO_ACTIVE_CARE_PLAN": 409,
    "ERR_NO_WAITLIST_ENTRY_FOR_UNIT": 409,
    "ERR_INVALID_TRANSFER_TARGET": 409,
    "ERR_INCOME_NOT_VERIFIED": 409,
    "ERR_DUPLICATE_WAITLIST_ENTRY": 409,
    "ERR_CLAIM_PERIOD_OVERLAP": 409,
    "ERR_CLAIM_MONTH_MISMATCH": 409,
    "ERR_CENSUS_DAY_ALREADY_CLAIMED": 409,
    "ERR_CLAIM_MONTH_NOT_CLOSED": 409,
    "ERR_BED_HOLD_OVERLAP": 409,
    "ERR_DATE_OUT_OF_RANGE": 409,
    "ERR_NO_AVAILABLE_BED": 409,
    "ERR_BED_HOLD_EXHAUSTED": 409,
    "ERR_CLAIM_CENSUS_EMPTY": 409,
    "ERR_TRUST_FUND_INSUFFICIENT": 409,
    "ERR_PNA_RESERVE_BREACH": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.status = ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request rejected: %s." % words


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ------------------------------------------------------------- envelope ----
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def object_response(data, status=200):
    return jsonify({"meta": base_meta(), "response_type": "object", "data": data}), status


def array_response(rows, total, limit, offset, status=200):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), status


def error_response(error_id, message=None, status=None):
    err = ApiError(error_id, message)
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), (status or err.status)


# ------------------------------------------------------------------ auth ----
def actor():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Missing or unrecognised X-User-ID / X-User-Role headers.")
    return user_id, role


def guard(*allowed):
    """Ladder rungs 1 and 2: authenticate, then authorise by role."""
    user_id, role = actor()
    if role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED", "Role %s may not perform this operation." % role)
    return user_id, role


# ------------------------------------------------------- request parsing ----
def json_body():
    if not request.data:
        return {}
    parsed = request.get_json(silent=True, force=True)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _bad(name, detail):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, detail))


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def present(body, name):
    return name in body and body[name] is not None


def f_str(body, name, min_len=1, max_len=None, required=True, default=None):
    if not present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if min_len is not None and len(value.strip()) < min_len:
        _bad(name, "must be at least %d characters and not blank" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(name, "must be at most %d characters" % max_len)
    return value


def f_enum(body, name, allowed, required=True, default=None):
    if not present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def f_int(body, name, minimum=None, maximum=None, required=True, default=None):
    if not present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not is_int(value):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be <= %d" % maximum)
    return value


def f_bool(body, name, required=True, default=None):
    if not present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def f_number(body, name, minimum=None, maximum=None, decimals=None, required=True, default=None):
    if not present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be <= %s" % maximum)
    if decimals is not None:
        exponent = Decimal(str(value)).normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -decimals:
            _bad(name, "must carry at most %d decimal places" % decimals)
    return value


def f_date(body, name, required=True, default=None):
    if not present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str) or not DATE_RE.match(value) or parse_date(value) is None:
        _bad(name, "must be a calendar date in YYYY-MM-DD form")
    return value


def f_month(body, name, required=True, default=None):
    if not present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str) or not MONTH_RE.match(value):
        _bad(name, "must be a month in YYYY-MM form")
    return value


def f_datetime(body, name, required=True, default=None):
    if not present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    parsed = parse_iso_datetime(value)
    if parsed is None:
        _bad(name, "must be an ISO 8601 instant")
    return parsed


def f_id(body, name, required=True, default=None):
    if not present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str) or not value.strip():
        _bad(name, "must be a non-empty identifier string")
    return value


# ------------------------------------------------------ query parameters ----
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            _bad("limit", "must be an integer between 1 and 100")
        if str(raw).strip() != str(limit):
            _bad("limit", "must be an integer between 1 and 100")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            _bad("offset", "must be a non-negative integer")
        if str(raw).strip() != str(offset):
            _bad("offset", "must be a non-negative integer")
        if offset < 0:
            _bad("offset", "must be >= 0")
    return limit, offset


def q_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    _bad(name, "must be true or false")


def q_date(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if not DATE_RE.match(value) or parse_date(value) is None:
        _bad(name, "must be a calendar date in YYYY-MM-DD form")
    return value


def q_month(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if not MONTH_RE.match(value):
        _bad(name, "must be a month in YYYY-MM form")
    return value


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    page = rows[offset:offset + limit]
    return array_response([serializer(row) for row in page], total, limit, offset)
