"""Core infrastructure: in-memory store, logical clock, errors, envelope, auth, validation."""
import random
import re
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_CX_AUTHORITY = "CxAuthority"
ROLE_CONTRACTOR = "Contractor"
ROLE_DESIGN_TEAM = "DesignTeam"
ROLE_OWNER_REP = "OwnerRepresentative"

ALL_ROLES = [
    ROLE_PLATFORM_ADMIN,
    ROLE_CX_AUTHORITY,
    ROLE_CONTRACTOR,
    ROLE_DESIGN_TEAM,
    ROLE_OWNER_REP,
]

# ---------------------------------------------------------------------------
# Error catalogue (error_id -> http status)
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_VALIDATION": 400,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_REQUIREMENT_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_SUBMITTAL_NOT_FOUND": 404,
    "ERR_EQUIPMENT_NOT_FOUND": 404,
    "ERR_CHECKLIST_NOT_FOUND": 404,
    "ERR_TEST_NOT_FOUND": 404,
    "ERR_ISSUE_NOT_FOUND": 404,
    "ERR_DEFERRED_TEST_NOT_FOUND": 404,
    "ERR_DELIVERABLE_NOT_FOUND": 404,
    "ERR_CREDIT_NOT_FOUND": 404,
    "ERR_BASELINE_NOT_FOUND": 404,
    "ERR_PROJECT_SCOPE_MISMATCH": 409,
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_PROJECT_FROZEN": 409,
    "ERR_PHASE_NOT_ALLOWED": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_EQUIPMENT_NOT_READY": 409,
    "ERR_PLAN_NOT_APPROVED": 409,
    "ERR_PLAN_PIN_STALE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_RETEST_EVIDENCE_REQUIRED": 422,
    "ERR_SAFETY_ITEM_FAILED": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_WITNESS_WINDOW_CONFLICT": 409,
    "ERR_SEASONAL_WINDOW_CONFLICT": 409,
    "ERR_OUTSIDE_SEASONAL_WINDOW": 409,
    "ERR_RETEST_SCOPE_MISMATCH": 422,
    "ERR_REQUIREMENT_NOT_PINNED": 422,
    "ERR_EVIDENCE_REF_INVALID": 422,
    "ERR_CHECKLIST_EMPTY": 422,
    "ERR_CHECKLIST_INCOMPLETE": 422,
    "ERR_DUPLICATE_ITEM_CODE": 422,
    "ERR_ITEM_NOT_FOUND": 422,
    "ERR_EVIDENCE_INSUFFICIENT": 422,
    "ERR_TRAINING_COVERAGE_INSUFFICIENT": 422,
    "ERR_REVIEW_ROUNDS_EXCEEDED": 422,
    "ERR_RETRO_ONLY": 422,
    "ERR_VARIANT_NOT_PERMITTED": 422,
    "ERR_RETAINAGE_CAP_EXCEEDED": 422,
    "ERR_ACCEPTANCE_SCORE_TOO_LOW": 422,
    "ERR_OPEN_BLOCKING_ISSUES": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def D(value):
    """Decimal from any numeric-ish value, without float artefacts."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimal places. Returns Decimal."""
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def num(value):
    """Convert a Decimal to a JSON-friendly number."""
    if isinstance(value, Decimal):
        f = float(value)
        return f
    return value


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------
_TS_LOCK = threading.Lock()
_last_wall_ms = 0

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d{1,9})?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)


def fmt_dt(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, offset = m.groups()
    try:
        micro = 0
        if frac:
            micro = int(round(float(frac) * 1_000_000))
            if micro >= 1_000_000:
                micro = 999_999
        dt = datetime(
            int(year), int(month), int(day), int(hour), int(minute),
            int(second or 0), micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * delta
    return dt


def wall_now_iso():
    """Strictly increasing wall-clock timestamp at millisecond resolution."""
    global _last_wall_ms
    with _TS_LOCK:
        ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if ms <= _last_wall_ms:
            ms = _last_wall_ms + 1
        _last_wall_ms = ms
    return fmt_dt(datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class _Clock:
    def __init__(self):
        self.current = CLOCK_EPOCH

    def now(self):
        return self.current

    def now_iso(self):
        return fmt_dt(self.current)

    def set(self, dt):
        self.current = dt


clock = _Clock()


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.projects = {}
        self.requirements = {}
        self.plans = {}
        self.submittals = {}
        self.equipment = {}
        self.checklists = {}
        self.tests = {}
        self.issues = {}
        self.deferred_tests = {}
        self.deliverables = {}
        self.credits = {}
        self.evidence = {}
        self.baselines = {}
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_row(collection, fields):
    ts = wall_now_iso()
    row = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    row.update(fields)
    row["_seq"] = db.next_seq()
    collection[row["id"]] = row
    return row


def touch(row):
    """Bump version / updated_at once per request for a non-project row."""
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    if row["id"] in touched:
        row["updated_at"] = wall_now_iso()
        return
    touched.add(row["id"])
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = wall_now_iso()


def touch_updated(row):
    row["updated_at"] = wall_now_iso()


def bump_project(project):
    """Unconditional CxProject.version increment (see PRD 2.8)."""
    project["version"] = project.get("version", 1) + 1
    project["updated_at"] = wall_now_iso()


def sorted_rows(rows):
    return sorted(rows, key=lambda r: r["_seq"])


def public(row):
    if row is None:
        return None
    out = {}
    for k, v in row.items():
        if k.startswith("_"):
            continue
        if isinstance(v, list):
            out[k] = [dict(x) if isinstance(x, dict) else x for x in v]
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = offset + len(rows) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Auth (PRD 2.1 / 2.5 checks 1-3)
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "Unknown role '%s'." % role)
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED", "Role '%s' may not perform this operation." % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def actor():
    return g.user_id


# ---------------------------------------------------------------------------
# Body / query validation (PRD 2.5 check 5)
# ---------------------------------------------------------------------------
MISSING = object()


def body_json():
    data = request.get_json(silent=True, force=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def _present(body, name):
    return name in body and body[name] is not None


def v_string(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            fail("ERR_VALIDATION", "Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "Field '%s' must be a string." % name)
    return value


def v_enum(body, name, allowed, required=True, default=None):
    if not _present(body, name):
        if required:
            fail("ERR_VALIDATION", "Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_VALIDATION", "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def v_bool(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            fail("ERR_VALIDATION", "Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        fail("ERR_VALIDATION", "Field '%s' must be a boolean." % name)
    return value


def v_int(body, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        if required:
            fail("ERR_VALIDATION", "Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_VALIDATION", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "Field '%s' must be <= %s." % (name, maximum))
    return value


def v_number(body, name, required=True, default=None, minimum=None, maximum=None,
             exclusive_minimum=None):
    if not _present(body, name):
        if required:
            fail("ERR_VALIDATION", "Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_VALIDATION", "Field '%s' must be a number." % name)
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        fail("ERR_VALIDATION", "Field '%s' must be a finite number." % name)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "Field '%s' must be >= %s." % (name, minimum))
    if exclusive_minimum is not None and value <= exclusive_minimum:
        fail("ERR_VALIDATION", "Field '%s' must be > %s." % (name, exclusive_minimum))
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "Field '%s' must be <= %s." % (name, maximum))
    return value


def v_datetime(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            fail("ERR_VALIDATION", "Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "Field '%s' must be an ISO 8601 UTC datetime string." % name)
    parsed = parse_dt(value)
    if parsed is None:
        fail("ERR_VALIDATION", "Field '%s' must be an ISO 8601 UTC datetime string." % name)
    return parsed


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_VALIDATION", "Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("ERR_VALIDATION", "Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(rows):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, limit, offset, total


def q(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def q_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    low = value.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    return None
