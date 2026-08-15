"""The validation pipeline (PRD 2.9).

Order of refusal, applied by every endpoint in strict sequence:

0. ERR_VALIDATION (400)  -- malformed payload: missing required field, unknown
   field, invalid enum member, out-of-range scalar.  Fires "as the payload is
   parsed", before the pipeline proper.
1. ERR_UNAUTHENTICATED (401) -- X-User-ID / X-User-Role present, role known.
2. ERR_FORBIDDEN (403) -- role permitted for the endpoint; entity-backed
   identity pins (Operator X-User-ID must be an existing Employee and equal a
   pinned employee field; ContractorRep X-User-ID must equal the pinned
   contractor field).
3. ERR_NOT_FOUND (404) -- path id and body references exist.
4. ERR_STALE_VERSION (412) -- the two OCC-guarded writes.
5. ERR_INVALID_STATE (409) -- source state permits the transition.
6. safety/compliance gates (422 / 409).
7. ERR_INVALID_WINDOW (422) / ERR_PERMIT_OUTSIDE_WINDOW (409).
8. ERR_PERMIT_WINDOW_CONFLICT / ERR_DRILL_GAP_VIOLATION (409).
9. ERR_CROSS_FACILITY_REFERENCE (422).
10. fiscal / quantity rules (422 / 409).

Steps 0-4 live here as reusable helpers; the rest live beside the workflow
that owns them.
"""
from functools import wraps

from flask import request

from errors import ApiError
from store import db
from util import parse_instant, to_decimal

ROLES = frozenset(
    [
        "FacilityAdmin",
        "PsCoordinator",
        "MaintenanceLead",
        "ComplianceOfficer",
        "Operator",
        "ContractorRep",
    ]
)

ALL_ROLES = ROLES  # GET endpoints: any authenticated role

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# Enum member sets (SCAFFOLD 1.1) --------------------------------------------
ENUMS = {
    "equipment_type": ("VESSEL", "COMPRESSOR", "PIPING_CIRCUIT", "PRV"),
    "inspection_method": ("FIXED", "CONDITION_BASED"),
    "doc_type": ("PID", "PSV_CALC", "RELIEF_DESIGN"),
    "adjustment_type": ("ADD", "REMOVE"),
    "topic": ("PSM_OVERVIEW", "AMMONIA_OPERATOR", "EMERGENCY_RESPONSE"),
    "drill_type": ("TABLETOP", "FIELD", "EVACUATION"),
    "severity": ("NEAR_MISS", "RECORDABLE", "REPORTABLE"),
    "employment_status": ("ACTIVE", "INACTIVE"),
    "system_to_status": ("IN_SERVICE", "OUT_OF_SERVICE", "DECOMMISSIONED"),
    "inspection_result": ("PASS", "FAIL"),
}


class Ctx(object):
    __slots__ = ("user_id", "role", "body", "args")

    def __init__(self, user_id, role, body, args):
        self.user_id = user_id
        self.role = role
        self.body = body
        self.args = args


# ---------------------------------------------------------------------------
# step 0 -- payload schema
# ---------------------------------------------------------------------------
def bad_request(message="The request failed schema or range validation."):
    raise ApiError("ERR_VALIDATION", message)


def read_body():
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload
    return {}


def schema_check(body, allowed, required):
    """Step 0: reject unknown fields, then missing required fields."""
    for key in body:
        if key not in allowed:
            bad_request("Unknown field '%s'." % key)
    for field in required:
        if field not in body or body[field] is None:
            bad_request("Required field '%s' is missing." % field)


def opt_present(body, field):
    return field in body and body[field] is not None


def req_string(body, field):
    value = body[field]
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % field)
    return value


def opt_string(body, field, default=None):
    if not opt_present(body, field):
        return default
    return req_string(body, field)


def as_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    return None


def req_int(body, field, minimum=None, maximum=None):
    value = as_int(body[field])
    if value is None:
        bad_request("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        bad_request("Field '%s' is below its declared minimum." % field)
    if maximum is not None and value > maximum:
        bad_request("Field '%s' is above its declared maximum." % field)
    return value


def req_number(body, field):
    value = to_decimal(body[field])
    if value is None:
        bad_request("Field '%s' must be a number." % field)
    return value


def opt_number(body, field, default):
    if not opt_present(body, field):
        return default
    return req_number(body, field)


def opt_bool(body, field, default):
    if not opt_present(body, field):
        return default
    value = body[field]
    if not isinstance(value, bool):
        bad_request("Field '%s' must be a boolean." % field)
    return value


def req_instant(body, field):
    value = parse_instant(body[field])
    if value is None:
        bad_request("Field '%s' must be an ISO 8601 instant." % field)
    return value


def req_enum(body, field, enum_key=None):
    value = req_string(body, field)
    if value not in ENUMS[enum_key or field]:
        bad_request("Field '%s' carries a value outside its declared member set." % field)
    return value


def opt_enum(body, field, default, enum_key=None):
    if not opt_present(body, field):
        return default
    return req_enum(body, field, enum_key)


def req_str_list(body, field):
    value = body[field]
    if not isinstance(value, list):
        bad_request("Field '%s' must be an array." % field)
    for item in value:
        if not isinstance(item, str):
            bad_request("Field '%s' must be an array of strings." % field)
    return value


# ---------------------------------------------------------------------------
# step 1 + step 2 (role gate)
# ---------------------------------------------------------------------------
def authenticate(body):
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if user_id is None or user_id == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    return Ctx(user_id, role, body, request.args)


def operator_employee(ctx):
    """Entity-backed identity (PRD 2.1): an Operator's X-User-ID must be an
    existing Employee.id.  Enforced on every Operator write."""
    if ctx.role != "Operator":
        return None
    employee = db.employees.get(ctx.user_id)
    if employee is None:
        raise ApiError(
            "ERR_FORBIDDEN",
            "An Operator's X-User-ID must reference an existing Employee.",
        )
    return employee


def endpoint(roles, schema=None):
    """Step 0 (schema, when declared) -> step 1 (auth) -> step 2 (role).

    `schema` is (allowed_fields, required_fields) for write endpoints.
    """
    allowed = frozenset(roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(**kw):
            body = read_body() if schema is not None else {}
            if schema is not None:
                schema_check(body, schema[0], schema[1])
            ctx = authenticate(body)
            if ctx.role not in allowed:
                raise ApiError("ERR_FORBIDDEN")
            return fn(ctx, **kw)

        return wrapper

    return deco


# ---------------------------------------------------------------------------
# step 3 -- existence
# ---------------------------------------------------------------------------
def path_row(collection, value):
    row = getattr(db, collection).get(value)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "No %s record has id %s." % (collection, value))
    return row


def body_row(body, collection, field):
    """Body foreign key that must resolve; null/absent handled by the caller."""
    value = body.get(field)
    row = getattr(db, collection).get(value) if isinstance(value, str) else None
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "Field '%s' references no existing record." % field)
    return row


# ---------------------------------------------------------------------------
# step 4 -- optimistic concurrency
# ---------------------------------------------------------------------------
def occ(ctx, field, parent_row):
    expected = req_int(ctx.body, field)
    if expected != parent_row["version"]:
        raise ApiError("ERR_STALE_VERSION")


# ---------------------------------------------------------------------------
# pagination and list filters
# ---------------------------------------------------------------------------
def _query_int(args, name):
    raw = args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(str(raw).strip())
    except (ValueError, TypeError):
        bad_request("Query parameter '%s' must be an integer." % name)


def pagination(ctx):
    limit = _query_int(ctx.args, "limit")
    offset = _query_int(ctx.args, "offset")
    if limit is None:
        limit = PAGE_LIMIT_DEFAULT
    elif limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
        bad_request("Query parameter 'limit' is out of bounds.")
    if offset is None:
        offset = PAGE_OFFSET_DEFAULT
    elif offset < 0:
        bad_request("Query parameter 'offset' is out of bounds.")
    return limit, offset


def apply_filters(rows, ctx, spec):
    """spec: list of (query_param, row_field, enum_members_or_None).  An
    enum-valued filter carrying a value outside its member set is a 400."""
    for param, field, members in spec:
        raw = ctx.args.get(param)
        if raw is None or raw == "":
            continue
        if members is not None and raw not in members:
            bad_request("Query parameter '%s' carries an unknown value." % param)
        rows = [r for r in rows if r.get(field) == raw]
    return rows


def paginate(rows, limit, offset):
    return rows[offset : offset + limit]
