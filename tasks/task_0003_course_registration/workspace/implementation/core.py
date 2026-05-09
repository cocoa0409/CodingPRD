"""Core: db, envelope, errors, auth, helpers."""
import secrets
import string
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, request, jsonify

# ---------------------------------------------------------------------------
# Constants from PRD/SCAFFOLD
# ---------------------------------------------------------------------------
APPROVAL_TIMEOUT_SECONDS = 86400

W_YEAR = 10
W_GAP = 15
W_PREREQ = 8
W_FRAUD = 2
FRAUD_GRACE = 10

REC_W_GAP = 100
REC_W_PREREQ_UNLOCK = 30
REC_W_TIME_CONFLICT = 50
REC_TOP_K = 5

RAPID_SUBMIT_WINDOW_SECONDS = 60
RAPID_SUBMIT_LIMIT = 10
RAPID_SUBMIT_PENALTY = 5
UNAUTHORIZED_DEPT_PENALTY = 8

CREDIT_TIER = {1: 18, 2: 20, 3: 22, 4: 24, 5: 24, 6: 24}

ROLE_REGISTRAR = "Registrar"
ROLE_STUDENT = "Student"
ROLE_PROFESSOR = "Professor"
ROLE_FINANCE = "Finance"
VALID_ROLES = {ROLE_REGISTRAR, ROLE_STUDENT, ROLE_PROFESSOR, ROLE_FINANCE}

DOWNSTREAM_ALL = ["ACADEMIC_AFFAIRS", "FINANCE", "LIBRARY", "DORMITORY"]
DOWNSTREAM_FINANCE = ["FINANCE"]
DOWNSTREAM_PAID = ["FINANCE", "LIBRARY", "DORMITORY"]
DOWNSTREAM_OVER_LIMIT = ["ACADEMIC_AFFAIRS", "FINANCE"]

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Registry of error_id -> http for canonical lookups; used as documentation only.
ERROR_CATALOG = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_NOT_OWNER": 403,
    "ERR_NOT_DESIGNATED_SIGNER": 403,
    "ERR_STUDENT_NOT_FOUND": 404,
    "ERR_PROFESSOR_NOT_FOUND": 404,
    "ERR_DEPARTMENT_NOT_FOUND": 404,
    "ERR_CAMPUS_NOT_FOUND": 404,
    "ERR_TERM_NOT_FOUND": 404,
    "ERR_COURSE_NOT_FOUND": 404,
    "ERR_OFFERING_NOT_FOUND": 404,
    "ERR_REQUEST_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_GRANT_NOT_FOUND": 404,
    "ERR_LAB_EQUIPMENT_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_TERM_NOT_OPEN_FOR_REGISTRATION": 409,
    "ERR_TERM_LOCKED_FOR_CANCEL": 409,
    "ERR_TERM_NOT_READY_FOR_CONCLUDE": 409,
    "ERR_OFFERING_NOT_OPEN": 409,
    "ERR_INVALID_STATE_FOR_SETTLE": 409,
    "ERR_REFERENTIAL_INTEGRITY": 422,
    "ERR_SIGNER_NOT_IN_HOME_DEPARTMENT": 422,
    "ERR_PRIMARY_SIGNER_IS_CHAIR": 422,
    "ERR_SECONDARY_SIGNER_NOT_CHAIR": 422,
    "ERR_CROSS_DEPARTMENT_ACCESS_DENIED": 403,
    "ERR_PREREQUISITE_NOT_MET": 422,
    "ERR_TIME_CONFLICT": 409,
    "ERR_COMMUTE_INFEASIBLE": 409,
    "ERR_EXAM_TIME_CONFLICT": 409,
    "ERR_LAB_EQUIPMENT_CONFLICT": 409,
    "ERR_INSTRUCTOR_TEACHING_LOAD_EXCEEDED": 409,
    "ERR_CREDIT_QUOTA_EXCEEDED": 402,
    "ERR_RATE_LIMITED": 429,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_PROMOTION_RACE_LOST": 409,
    "ERR_CAPACITY_CASCADE_RACE_RETRY": 409,
    "ERR_INVALID_PAGINATION_PARAMETERS": 400,
}


def err(error_id: str, message: str = "") -> ApiError:
    return ApiError(error_id, ERROR_CATALOG[error_id], message)


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
class DB:
    def __init__(self):
        self.reset()

    def reset(self):
        self.departments = {}
        self.campuses = {}
        self.students = {}
        self.professors = {}
        self.terms = {}
        self.courses = {}
        self.course_offerings = {}
        self.lab_equipment = {}
        self.enrollment_requests = {}
        self.waitlist_entries = {}
        self.over_limit_applications = {}
        self.credit_equivalence_policies = {}
        self.department_access_grants = {}
        self.sync_events = []
        self.clock = 0  # logical clock; advanced by /_clock/advance


db = DB()
LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# Helpers: ids, timestamps, money
# ---------------------------------------------------------------------------
def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def now_iso() -> str:
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def round2(value):
    if value is None:
        return None
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def sum_round2(values) -> float:
    total = Decimal("0")
    for v in values:
        if v is None:
            continue
        total += Decimal(str(v))
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def sum_credits(values) -> float:
    """Add credits already at 2dp, returning float at 2dp."""
    return sum_round2(values)


def trunc_int(value) -> int:
    """Truncate toward zero."""
    if value >= 0:
        return int(value)
    return -int(-value)


def stamp_create():
    """Return common fields dict for a newly created entity."""
    iso = now_iso()
    return {
        "id": new_id(),
        "created_at": iso,
        "updated_at": iso,
        "version": 1,
    }


def stamp_create_immutable():
    """Common fields for entities that lack updated_at/version."""
    return {"id": new_id(), "created_at": now_iso()}


def bump(entity: dict):
    """Mutation: refresh updated_at and version."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": getattr(g, "api_request_id", None) or new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, http=200, pagination=None):
    rt = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(pagination),
        "response_type": rt,
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = http
    return resp


def error_response(api_err: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    resp = jsonify(body)
    resp.status_code = api_err.http_status
    return resp


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def parse_auth():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    return user_id, role


def require_roles(*allowed):
    user_id, role = parse_auth()
    if role not in allowed:
        raise err("ERR_INSUFFICIENT_PERMISSIONS")
    return user_id, role


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err("ERR_INVALID_PAGINATION_PARAMETERS")
    if limit < 1 or limit > 100 or offset < 0:
        raise err("ERR_INVALID_PAGINATION_PARAMETERS")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    sliced = items[offset : offset + limit]
    return sliced, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


# ---------------------------------------------------------------------------
# Body helpers
# ---------------------------------------------------------------------------
def get_json_body():
    return request.get_json(silent=True) or {}


def require_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise err("ERR_REFERENTIAL_INTEGRITY", f"missing field: {name}")
    return body[name]


def maybe(body: dict, name, default=None):
    return body.get(name, default)
