"""Core infrastructure: in-memory store, logical clock, response envelope,
error catalogue, authentication/RBAC and request-body validation helpers.

Storage is process-local and in-memory only: every fresh boot of start.sh
starts with a completely empty store.  Nothing is seeded here or anywhere else.
"""
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLE_RECRUITER = "Recruiter"
ROLE_DER = "DER"
ROLE_SAFETY = "SafetyDirector"
ROLE_AUDITOR = "ComplianceAuditor"
ROLE_SCHOOL = "SchoolCoordinator"
ROLE_APPLICANT = "Applicant"

ALL_ROLES = [
    ROLE_RECRUITER,
    ROLE_DER,
    ROLE_SAFETY,
    ROLE_AUDITOR,
    ROLE_SCHOOL,
    ROLE_APPLICANT,
]

HDR_USER_ID = "X-User-ID"
HDR_USER_ROLE = "X-User-Role"

# ---------------------------------------------------------------------------
# Error catalogue (PRD 5)
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_VALIDATION": 422,
    "ERR_CARRIER_NOT_FOUND": 404,
    "ERR_APPLICANT_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_VERIFICATION_NOT_FOUND": 404,
    "ERR_SCREENING_CHECK_NOT_FOUND": 404,
    "ERR_CLEARINGHOUSE_QUERY_NOT_FOUND": 404,
    "ERR_DRUG_TEST_NOT_FOUND": 404,
    "ERR_ROAD_TEST_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_DQ_FILE_NOT_FOUND": 404,
    "ERR_DQ_DOCUMENT_NOT_FOUND": 404,
    "ERR_TUITION_AGREEMENT_NOT_FOUND": 404,
    "ERR_HIRE_RECORD_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_DUPLICATE_DOT_NUMBER": 409,
    "ERR_DUPLICATE_ACTIVE_APPLICATION": 409,
    "ERR_APPLICATION_NOT_QUALIFIED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_CLEARINGHOUSE_PROHIBITED": 409,
    "ERR_CONSENT_NOT_GRANTED": 409,
    "ERR_CONSENT_EXPIRED": 409,
    "ERR_DRUG_TEST_NOT_NEGATIVE": 409,
    "ERR_MVR_POINTS_EXCEEDED": 409,
    "ERR_MVR_EXPIRED": 409,
    "ERR_MEDICAL_CERT_INVALID": 409,
    "ERR_EMPLOYMENT_HISTORY_INCOMPLETE": 409,
    "ERR_REVIEW_NOT_DUE": 409,
    "ERR_ORIENTATION_OVERLAP": 409,
    "ERR_EXAMINER_SLOT_CONFLICT": 409,
    "ERR_SESSION_AT_CAPACITY": 409,
    "ERR_ROAD_TEST_ATTEMPTS_EXHAUSTED": 409,
    "ERR_DQ_FILE_INCOMPLETE": 409,
    "ERR_REHIRE_INELIGIBLE": 409,
    "ERR_CARRIER_POSTURE_BLOCKED": 409,
    "ERR_NO_OPEN_REQUISITION": 409,
    "ERR_NO_CLAWBACK_TO_REVERSE": 409,
    "ERR_COMMITMENT_ALREADY_FULFILLED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5) — startup default is exactly 2026-08-01T00:00:00Z
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0)

_clock = {"now": CLOCK_DEFAULT}


def now():
    return _clock["now"]


def set_now(value):
    _clock["now"] = value


def today():
    return _clock["now"].date()


def fmt_instant(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_date(d):
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date_or_none(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def parse_instant_or_none(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        offset = parsed.utcoffset()
        parsed = parsed.replace(tzinfo=None) - offset
    return parsed


def d(value):
    """Coerce a stored ISO date string into a date object."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return parse_date_or_none(value)


def dt(value):
    """Coerce a stored ISO instant string into a datetime object."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return parse_instant_or_none(value)


def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def num(value, places):
    return float(round_half_up(value, places))


# ---------------------------------------------------------------------------
# In-memory store — empty on every boot
# ---------------------------------------------------------------------------
COLLECTIONS = [
    "carriers",
    "driver_applicants",
    "driver_applications",
    "employment_verifications",
    "screening_checks",
    "clearinghouse_queries",
    "drug_test_orders",
    "road_tests",
    "orientation_sessions",
    "orientation_enrollments",
    "dq_files",
    "dq_documents",
    "tuition_agreements",
    "hire_records",
]

DB = {name: {} for name in COLLECTIONS}
_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_row(collection, fields):
    stamp = fmt_instant(now())
    row = {"id": str(uuid.uuid4())}
    row.update(fields)
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = next_seq()
    DB[collection][row["id"]] = row
    try:
        g.touched.add(row["id"])
    except Exception:
        pass
    return row


def touch(row):
    """Mark a row mutated: version increments exactly once per request."""
    row["updated_at"] = fmt_instant(now())
    try:
        touched = g.touched
    except Exception:
        row["version"] += 1
        return row
    if row["id"] not in touched:
        touched.add(row["id"])
        row["version"] += 1
    return row


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def all_rows(collection):
    rows = list(DB[collection].values())
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_instant(now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(window)) < total
    body = {"meta": meta, "response_type": "array", "data": window}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Authentication / RBAC (validation priorities 1-3)
# ---------------------------------------------------------------------------
def require_roles(roles):
    user_id = request.headers.get(HDR_USER_ID)
    user_role = request.headers.get(HDR_USER_ROLE)
    if not user_id or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if not user_role or not str(user_role).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    if user_role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role.")
    if user_role not in roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint." % user_role)
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def actor_id():
    return g.user_id


def actor_role():
    return g.user_role


# ---------------------------------------------------------------------------
# Body / query parameter validation helpers (priorities 7 and 8)
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def _missing(payload, key):
    return key not in payload or payload[key] is None


def req_str(payload, key):
    if _missing(payload, key) or not isinstance(payload[key], str) or payload[key] == "":
        fail("ERR_VALIDATION", "Field '%s' must be a non-empty string." % key)
    return payload[key]


def opt_str(payload, key, default=None):
    if _missing(payload, key):
        return default
    if not isinstance(payload[key], str):
        fail("ERR_VALIDATION", "Field '%s' must be a string." % key)
    return payload[key]


def req_enum(payload, key, allowed):
    value = req_str(payload, key)
    if value not in allowed:
        fail("ERR_VALIDATION", "Field '%s' must be one of %s." % (key, sorted(allowed)))
    return value


def opt_enum(payload, key, allowed, default=None):
    if _missing(payload, key):
        return default
    return req_enum(payload, key, allowed)


def _as_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def req_int(payload, key, minimum=None, maximum=None):
    if _missing(payload, key):
        fail("ERR_VALIDATION", "Field '%s' is required." % key)
    value = _as_int(payload[key])
    if value is None:
        fail("ERR_VALIDATION", "Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "Field '%s' must be <= %s." % (key, maximum))
    return value


def opt_int(payload, key, minimum=None, maximum=None, default=None):
    if _missing(payload, key):
        return default
    return req_int(payload, key, minimum, maximum)


def req_bool(payload, key):
    if _missing(payload, key) or not isinstance(payload[key], bool):
        fail("ERR_VALIDATION", "Field '%s' must be a boolean." % key)
    return payload[key]


def opt_bool(payload, key, default=None):
    if _missing(payload, key):
        return default
    return req_bool(payload, key)


def req_date(payload, key):
    value = req_str(payload, key)
    parsed = parse_date_or_none(value)
    if parsed is None:
        fail("ERR_VALIDATION", "Field '%s' must be a YYYY-MM-DD calendar date." % key)
    return parsed


def opt_date(payload, key, default=None):
    if _missing(payload, key):
        return default
    return req_date(payload, key)


def req_instant(payload, key):
    value = req_str(payload, key)
    parsed = parse_instant_or_none(value)
    if parsed is None:
        fail("ERR_VALIDATION", "Field '%s' must be an ISO 8601 instant." % key)
    return parsed


def req_id_list(payload, key):
    if _missing(payload, key) or not isinstance(payload[key], list):
        fail("ERR_VALIDATION", "Field '%s' must be a list." % key)
    for item in payload[key]:
        if not isinstance(item, str) or not item:
            fail("ERR_VALIDATION", "Field '%s' must contain identifier strings." % key)
    return payload[key]


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "limit must be an integer.")
        if str(raw).strip() != str(limit):
            fail("ERR_VALIDATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_VALIDATION", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "offset must be an integer.")
        if str(raw).strip() != str(offset):
            fail("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            fail("ERR_VALIDATION", "offset must be >= 0.")
    return limit, offset


def qs(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


# ---------------------------------------------------------------------------
# Path / foreign-key resolution (priorities 5 and 6)
# ---------------------------------------------------------------------------
NOT_FOUND = {
    "carriers": "ERR_CARRIER_NOT_FOUND",
    "driver_applicants": "ERR_APPLICANT_NOT_FOUND",
    "driver_applications": "ERR_APPLICATION_NOT_FOUND",
    "employment_verifications": "ERR_VERIFICATION_NOT_FOUND",
    "screening_checks": "ERR_SCREENING_CHECK_NOT_FOUND",
    "clearinghouse_queries": "ERR_CLEARINGHOUSE_QUERY_NOT_FOUND",
    "drug_test_orders": "ERR_DRUG_TEST_NOT_FOUND",
    "road_tests": "ERR_ROAD_TEST_NOT_FOUND",
    "orientation_sessions": "ERR_SESSION_NOT_FOUND",
    "orientation_enrollments": "ERR_ENROLLMENT_NOT_FOUND",
    "dq_files": "ERR_DQ_FILE_NOT_FOUND",
    "dq_documents": "ERR_DQ_DOCUMENT_NOT_FOUND",
    "tuition_agreements": "ERR_TUITION_AGREEMENT_NOT_FOUND",
    "hire_records": "ERR_HIRE_RECORD_NOT_FOUND",
}


def must_get(collection, row_id):
    row = DB[collection].get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(NOT_FOUND[collection], "%s does not resolve." % collection)
    return row


def fk(payload, key, collection, required=True):
    """Resolve a body foreign key (priority 6) before shape checks (priority 7)."""
    if _missing(payload, key):
        if required:
            return None  # shape check will report ERR_VALIDATION later
        return None
    value = payload[key]
    if not isinstance(value, str) or value == "":
        return None
    return must_get(collection, value)
