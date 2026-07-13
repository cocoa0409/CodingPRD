"""Core primitives: errors, response envelope, logical clock, in-memory store,
auth/RBAC helpers, request validators, rounding helpers."""

import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLE_PRINCIPAL = "PrincipalArchitect"
ROLE_PM = "ProjectManager"
ROLE_STAFF = "StaffArchitect"
ROLE_CONSULTANT = "ConsultantRep"
ROLE_CLIENT = "ClientRep"

ALL_ROLES = (ROLE_PRINCIPAL, ROLE_PM, ROLE_STAFF, ROLE_CONSULTANT, ROLE_CLIENT)
READ_ROLES = ALL_ROLES


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def bad_request(msg="Malformed request."):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_dt(datetime.now(timezone.utc))


def parse_dt(value, field="timestamp"):
    if not isinstance(value, str) or not value.strip():
        raise bad_request("Field '%s' must be an ISO 8601 datetime string." % field)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise bad_request("Field '%s' is not a valid ISO 8601 datetime." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Rounding (PRD 2.6)
# ---------------------------------------------------------------------------
def d(value):
    return Decimal(str(value))


def round_half_up_int(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# In-memory store (empty at boot; every entity is created via the API)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.staff = {}
        self.consultants = {}
        self.projects = {}
        self.contracts = {}
        self.phases = {}
        self.drawings = {}
        self.time_entries = {}
        self.expenses = {}
        self.rfis = {}
        self.submittals = {}
        self.change_orders = {}
        self.invoices = {}
        self.permit_reviews = {}
        self.field_reports = {}
        self.clock = DEFAULT_CLOCK


db = Store()


def clock_now():
    return db.clock


def new_id():
    return str(uuid.uuid4())


def new_row(fields, versioned=True):
    row = {"id": new_id(), "created_at": now_iso()}
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row.update(fields)
    return row


def bump(row):
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 0) + 1


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
def _meta():
    rid = "req_" + "".join(
        random.choice(string.ascii_uppercase + string.digits) for _ in range(20)
    )
    return {"api_request_id": rid, "api_request_timestamp": now_iso()}


def respond(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def respond_list(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def respond_error(error_id, http_status, message):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        http_status,
    )


# ---------------------------------------------------------------------------
# Auth (PRD 2.7 steps 1-2)
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers.")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role %s may not call this endpoint." % role)
    return user_id, role


# ---------------------------------------------------------------------------
# Body / query validators (PRD 2.7 step 4)
# ---------------------------------------------------------------------------
def get_body():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise bad_request("Request body must be a JSON object.")
    return payload


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_str(body, key):
    value = body.get(key)
    if not isinstance(value, str) or value.strip() == "":
        raise bad_request("Field '%s' is required and must be a non-empty string." % key)
    return value


def opt_str(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    value = body[key]
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % key)
    return value


def req_int(body, key, minimum=None, maximum=None):
    value = body.get(key)
    if not _is_int(value):
        raise bad_request("Field '%s' is required and must be an integer." % key)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' must be <= %s." % (key, maximum))
    return value


def opt_int(body, key, default=0, minimum=None, maximum=None):
    if key not in body or body[key] is None:
        return default
    value = body[key]
    if not _is_int(value):
        raise bad_request("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' must be <= %s." % (key, maximum))
    return value


def opt_bool(body, key, default):
    if key not in body or body[key] is None:
        return default
    value = body[key]
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % key)
    return value


def req_enum(body, key, members):
    value = body.get(key)
    if not isinstance(value, str) or value not in members:
        raise bad_request("Field '%s' must be one of %s." % (key, ", ".join(members)))
    return value


def opt_enum(body, key, members, default):
    if key not in body or body[key] is None:
        return default
    value = body[key]
    if not isinstance(value, str) or value not in members:
        raise bad_request("Field '%s' must be one of %s." % (key, ", ".join(members)))
    return value


def req_dt_raw(body, key):
    """Returns (raw string, parsed datetime). The raw string is echoed back verbatim."""
    value = body.get(key)
    if not isinstance(value, str):
        raise bad_request("Field '%s' is required and must be an ISO 8601 string." % key)
    return value, parse_dt(value, key)


def req_to_status(body):
    value = body.get("to_status")
    if not isinstance(value, str) or value.strip() == "":
        raise bad_request("Field 'to_status' is required and must be a string.")
    return value


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise bad_request("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad_request("Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(rows):
    """Rows arrive in creation order (dict insertion order == created_at ASC)."""
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, limit, offset, total


# ---------------------------------------------------------------------------
# Lookups (PRD 2.7 steps 3 & 5)
# ---------------------------------------------------------------------------
_NOT_FOUND = {
    "project": "ERR_PROJECT_NOT_FOUND",
    "contract": "ERR_CONTRACT_NOT_FOUND",
    "phase": "ERR_PHASE_NOT_FOUND",
    "staff": "ERR_STAFF_NOT_FOUND",
    "consultant": "ERR_CONSULTANT_NOT_FOUND",
    "drawing": "ERR_DRAWING_NOT_FOUND",
    "time_entry": "ERR_TIME_ENTRY_NOT_FOUND",
    "expense": "ERR_EXPENSE_NOT_FOUND",
    "rfi": "ERR_RFI_NOT_FOUND",
    "submittal": "ERR_SUBMITTAL_NOT_FOUND",
    "change_order": "ERR_CHANGE_ORDER_NOT_FOUND",
    "invoice": "ERR_INVOICE_NOT_FOUND",
    "permit_review": "ERR_PERMIT_REVIEW_NOT_FOUND",
    "field_report": "ERR_FIELD_REPORT_NOT_FOUND",
}

_COLLECTIONS = {
    "project": lambda: db.projects,
    "contract": lambda: db.contracts,
    "phase": lambda: db.phases,
    "staff": lambda: db.staff,
    "consultant": lambda: db.consultants,
    "drawing": lambda: db.drawings,
    "time_entry": lambda: db.time_entries,
    "expense": lambda: db.expenses,
    "rfi": lambda: db.rfis,
    "submittal": lambda: db.submittals,
    "change_order": lambda: db.change_orders,
    "invoice": lambda: db.invoices,
    "permit_review": lambda: db.permit_reviews,
    "field_report": lambda: db.field_reports,
}


def find(kind, entity_id):
    collection = _COLLECTIONS[kind]()
    row = collection.get(entity_id) if isinstance(entity_id, str) else None
    if row is None:
        raise ApiError(_NOT_FOUND[kind], 404, "%s not found." % kind)
    return row


def fk(kind, body, key, required=True):
    """Resolve a foreign key supplied in the request body."""
    value = body.get(key)
    if value is None:
        if required:
            raise bad_request("Field '%s' is required." % key)
        return None
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string id." % key)
    return find(kind, value)
