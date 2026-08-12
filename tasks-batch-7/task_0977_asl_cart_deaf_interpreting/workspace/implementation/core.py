"""Core infrastructure: logical clock, in-memory store, errors, envelope,
auth context, and request-body validation helpers."""
import uuid
from datetime import datetime, timedelta, timezone

from flask import jsonify, request


# --------------------------------------------------------------------------
# Logical clock (never wall-clock). Startup default: 2026-05-01T00:00:00Z.
# --------------------------------------------------------------------------
class _Clock:
    def __init__(self):
        self.current = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


CLOCK = _Clock()


def now():
    return CLOCK.current


# --------------------------------------------------------------------------
# In-memory store. Starts EMPTY on every boot — no seeding.
# --------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.orgs = {}
        self.rate_cards = {}
        self.interpreters = {}
        self.certifications = {}
        self.availability_windows = {}
        self.requests = {}
        self.assignments = {}
        self.encounters = {}
        self.invoices = {}
        self.complaints = {}
        self.credit_memos = {}
        self.strikes = {}
        self.reports = {}
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


DB = Store()


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


# Error id constants (catalog from scaffold/PRD)
E_HEADERS = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"      # 400
E_INVALID = "ERR_INVALID_REQUEST"                             # 400
E_ONSITE_ADDR = "ERR_ONSITE_ADDRESS_REQUIRED"                 # 400
E_ROLE = "ERR_UNAUTHORIZED_ROLE"                              # 403
E_OWNERSHIP = "ERR_FORBIDDEN_OWNERSHIP"                       # 403
E_ORG_NF = "ERR_ORG_NOT_FOUND"                                # 404
E_CARD_NF = "ERR_RATE_CARD_NOT_FOUND"                         # 404
E_INTERP_NF = "ERR_INTERPRETER_NOT_FOUND"                     # 404
E_CERT_NF = "ERR_CERTIFICATION_NOT_FOUND"                     # 404
E_WINDOW_NF = "ERR_AVAILABILITY_WINDOW_NOT_FOUND"             # 404
E_REQUEST_NF = "ERR_REQUEST_NOT_FOUND"                        # 404
E_ASSIGN_NF = "ERR_ASSIGNMENT_NOT_FOUND"                      # 404
E_ENCOUNTER_NF = "ERR_ENCOUNTER_NOT_FOUND"                    # 404
E_INVOICE_NF = "ERR_INVOICE_NOT_FOUND"                        # 404
E_COMPLAINT_NF = "ERR_COMPLAINT_NOT_FOUND"                    # 404
E_MEMO_NF = "ERR_CREDIT_MEMO_NOT_FOUND"                       # 404
E_STRIKE_NF = "ERR_STRIKE_NOT_FOUND"                          # 404
E_REPORT_NF = "ERR_REPORT_NOT_FOUND"                          # 404
E_ORG_NOT_ACTIVE = "ERR_ORG_NOT_ACTIVE"                       # 409
E_INTERP_NOT_ACTIVE = "ERR_INTERPRETER_NOT_ACTIVE"            # 409
E_CARD_RETIRED = "ERR_RATE_CARD_ALREADY_RETIRED"              # 409
E_REQ_NOT_DRAFT = "ERR_REQUEST_NOT_DRAFT"                     # 409
E_REQ_NOT_CANCELLABLE = "ERR_REQUEST_NOT_CANCELLABLE"         # 409
E_REQ_NOT_OFFERABLE = "ERR_REQUEST_NOT_OFFERABLE"             # 409
E_MAX_OFFERS = "ERR_MAX_OFFER_ATTEMPTS_REACHED"               # 409
E_ASN_NOT_OFFERED = "ERR_ASSIGNMENT_NOT_OFFERED"              # 409
E_ASN_NOT_ACCEPTED = "ERR_ASSIGNMENT_NOT_ACCEPTED"            # 409
E_ASN_NOT_CONFIRMED = "ERR_ASSIGNMENT_NOT_CONFIRMED"          # 409
E_ASN_NOT_ON_SITE = "ERR_ASSIGNMENT_NOT_ON_SITE"              # 409
E_ENC_VERIFIED = "ERR_ENCOUNTER_ALREADY_VERIFIED"             # 409
E_ENC_NOT_VERIFIED = "ERR_ENCOUNTER_NOT_VERIFIED"             # 409
E_INV_NOT_DRAFT = "ERR_INVOICE_NOT_DRAFT"                     # 409
E_INV_NOT_ISSUED = "ERR_INVOICE_NOT_ISSUED"                   # 409
E_INV_NOT_DISPUTED = "ERR_INVOICE_NOT_DISPUTED"               # 409
E_COMPLAINT_STATE = "ERR_COMPLAINT_INVALID_STATE"             # 409
E_COMPLAINT_REOPENED = "ERR_COMPLAINT_ALREADY_REOPENED"       # 409
E_MEMO_NOT_OPEN = "ERR_CREDIT_MEMO_NOT_OPEN"                  # 409
E_STRIKE_NOT_ACTIVE = "ERR_STRIKE_NOT_ACTIVE"                 # 409
E_STRIKES_AT_LIMIT = "ERR_ACTIVE_STRIKES_AT_LIMIT"            # 409
E_WINDOW_OVERLAP = "ERR_AVAILABILITY_WINDOW_OVERLAP"          # 409
E_DOUBLE_BOOKED = "ERR_INTERPRETER_DOUBLE_BOOKED"             # 409
E_VRI_CAPACITY = "ERR_VRI_CAPACITY_EXCEEDED"                  # 409
E_INVOICE_EXISTS = "ERR_INVOICE_ALREADY_EXISTS"               # 409
E_MODALITY = "ERR_MODALITY_NOT_OFFERED"                       # 422
E_VRI_CERT = "ERR_VRI_CERTIFICATION_REQUIRED"                 # 422
E_CREDENTIAL = "ERR_CREDENTIAL_INSUFFICIENT"                  # 422
E_QUALITY = "ERR_QUALITY_BELOW_THRESHOLD"                     # 422
E_SCHEDULE = "ERR_INVALID_SCHEDULE"                           # 422
E_CHECKIN_WINDOW = "ERR_CHECK_IN_WINDOW_VIOLATION"            # 422
E_NO_SHOW_EARLY = "ERR_NO_SHOW_TOO_EARLY"                     # 422
E_NO_COVERAGE = "ERR_NO_AVAILABILITY_COVERAGE"                # 422
E_OVERPAY = "ERR_PAYMENT_EXCEEDS_AMOUNT_DUE"                  # 422
E_CREDIT_LIMIT = "ERR_CREDIT_LIMIT_EXCEEDED"                  # 402
E_STALE_REQUEST = "ERR_STALE_REQUEST_VERSION"                 # 412
E_STALE_ORG = "ERR_STALE_ORG_VERSION"                         # 412


# --------------------------------------------------------------------------
# Ids / timestamps
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def new_req_id():
    return "req_" + uuid.uuid4().hex[:24]


def iso(dt):
    """Render an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field):
    if not isinstance(value, str):
        err(E_INVALID, 400, f"Field '{field}' must be an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        err(E_INVALID, 400, f"Field '{field}' is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------
def envelope(data, code=200, pagination=None, response_type=None):
    if response_type is None:
        response_type = "array" if isinstance(data, list) else "object"
    meta = {"api_request_id": new_req_id(), "api_request_timestamp": iso(now())}
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), code


def error_envelope(api_err):
    body = {
        "meta": {"api_request_id": new_req_id(), "api_request_timestamp": iso(now())},
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    return jsonify(body), api_err.http_status


# --------------------------------------------------------------------------
# Auth context (validation tier 1 and tier 3)
# --------------------------------------------------------------------------
DECLARED_ROLES = {"PlatformAdmin", "OrgRequester", "Interpreter",
                  "QualityReviewer", "BillingClerk", "Any"}


def auth_ctx():
    """Validate X-User-ID / X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in DECLARED_ROLES:
        err(E_HEADERS, 400,
            "X-User-ID and X-User-Role headers are required and role must be declared")
    return user_id, role


def require_role(role, *allowed):
    if role not in allowed:
        err(E_ROLE, 403, f"Role {role} is not permitted for this endpoint")


def check_ownership(condition):
    if not condition:
        err(E_OWNERSHIP, 403, "The acting user does not own the target resource")


# --------------------------------------------------------------------------
# Body parsing + field validators (validation tier 2)
# --------------------------------------------------------------------------
def get_body(allowed_fields=None, require=False):
    """Parse JSON object body. Unknown fields rejected when allowed_fields given."""
    raw = request.get_json(silent=True)
    if raw is None:
        if require:
            err(E_INVALID, 400, "Request body must be a JSON object")
        return {}
    if not isinstance(raw, dict):
        err(E_INVALID, 400, "Request body must be a JSON object")
    if allowed_fields is not None:
        for key in raw:
            if key not in allowed_fields:
                err(E_INVALID, 400, f"Unknown field '{key}'")
    return raw


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and v == v and v not in (float("inf"), float("-inf")))


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        err(E_INVALID, 400, f"Field '{field}' is required and must be a non-empty string")
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        err(E_INVALID, 400, f"Field '{field}' must be a string")
    return v


def req_int(body, field, minimum=None):
    v = body.get(field)
    if not _is_int(v):
        err(E_INVALID, 400, f"Field '{field}' is required and must be an integer")
    if minimum is not None and v < minimum:
        err(E_INVALID, 400, f"Field '{field}' must be >= {minimum}")
    return v


def opt_int(body, field, default=None, minimum=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not _is_int(v):
        err(E_INVALID, 400, f"Field '{field}' must be an integer")
    if minimum is not None and v < minimum:
        err(E_INVALID, 400, f"Field '{field}' must be >= {minimum}")
    return v


def req_num(body, field, minimum=None):
    v = body.get(field)
    if not _is_num(v):
        err(E_INVALID, 400, f"Field '{field}' is required and must be a number")
    if minimum is not None and v < minimum:
        err(E_INVALID, 400, f"Field '{field}' must be >= {minimum}")
    return v


def opt_num(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not _is_num(v):
        err(E_INVALID, 400, f"Field '{field}' must be a number")
    if minimum is not None and v < minimum:
        err(E_INVALID, 400, f"Field '{field}' must be >= {minimum}")
    if maximum is not None and v > maximum:
        err(E_INVALID, 400, f"Field '{field}' must be <= {maximum}")
    return v


def req_enum(body, field, domain):
    v = body.get(field)
    if not isinstance(v, str) or v not in domain:
        err(E_INVALID, 400, f"Field '{field}' must be one of {sorted(domain)}")
    return v


def opt_enum(body, field, domain, default=None):
    if field not in body or body[field] is None:
        return default
    return req_enum(body, field, domain)


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        err(E_INVALID, 400, f"Field '{field}' must be a boolean")
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    return req_bool(body, field)


def req_dt(body, field):
    if field not in body:
        err(E_INVALID, 400, f"Field '{field}' is required")
    return parse_dt(body[field], field)


def opt_dt(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return parse_dt(body[field], field)


def req_enum_list(body, field, domain):
    v = body.get(field)
    if not isinstance(v, list) or len(v) == 0:
        err(E_INVALID, 400, f"Field '{field}' must be a non-empty array")
    for item in v:
        if not isinstance(item, str) or item not in domain:
            err(E_INVALID, 400, f"Field '{field}' entries must be in {sorted(domain)}")
    return list(dict.fromkeys(v))


# --------------------------------------------------------------------------
# Pagination (limit/offset, defaults 10/0, limit in [1,100])
# --------------------------------------------------------------------------
def paginate(items):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        err(E_INVALID, 400, "Query parameter 'limit' must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        err(E_INVALID, 400, "Query parameter 'offset' must be an integer")
    if limit < 1 or limit > 100:
        err(E_INVALID, 400, "Query parameter 'limit' must be between 1 and 100")
    if offset < 0:
        err(E_INVALID, 400, "Query parameter 'offset' must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {"limit": limit, "offset": offset, "total_count": total,
            "has_more": offset + len(page) < total}
    return page, meta


def sort_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
