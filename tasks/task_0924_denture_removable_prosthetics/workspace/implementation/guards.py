"""The order of refusal -- the 31-rung ladder (PRD 2.10).

Rungs 1-9 plus the generic state rungs 10 and 12 live here as reusable
helpers; every route calls them in strict ladder order.  Route-specific rungs
(11, 13-31) live next to the workflow that owns them.
"""
from functools import wraps

from flask import request

import pconst
from errors import ApiError
from store import db
from util import parse_instant, to_decimal

# ---------------------------------------------------------------------------
# rung 4 -- path existence: which collection and which not-found code
# ---------------------------------------------------------------------------
PATH_ENTITY = {
    "patient_id": ("patients", "ERR_PATIENT_NOT_FOUND"),
    "case_id": ("cases", "ERR_CASE_NOT_FOUND"),
    "case_arch_id": ("arches", "ERR_ARCH_NOT_FOUND"),
    "lab_case_id": ("labcases", "ERR_LAB_CASE_NOT_FOUND"),
    "prosthesis_id": ("prostheses", "ERR_PROSTHESIS_NOT_FOUND"),
    "coverage_id": ("coverages", "ERR_RESOURCE_NOT_FOUND"),
    "lab_id": ("labs", "ERR_RESOURCE_NOT_FOUND"),
    "impression_id": ("impressions", "ERR_RESOURCE_NOT_FOUND"),
    "try_in_id": ("tryins", "ERR_RESOURCE_NOT_FOUND"),
    "service_id": ("services", "ERR_RESOURCE_NOT_FOUND"),
    "warranty_claim_id": ("warranty_claims", "ERR_RESOURCE_NOT_FOUND"),
    "remake_request_id": ("remake_requests", "ERR_RESOURCE_NOT_FOUND"),
    "predetermination_id": ("predeterminations", "ERR_RESOURCE_NOT_FOUND"),
    "claim_id": ("claims", "ERR_RESOURCE_NOT_FOUND"),
    "payment_plan_id": ("plans", "ERR_RESOURCE_NOT_FOUND"),
    "installment_id": ("installments", "ERR_RESOURCE_NOT_FOUND"),
}

# ---------------------------------------------------------------------------
# rung 6 -- body foreign keys: which collection each body FK names
# ---------------------------------------------------------------------------
BODY_FK = {
    "patient_id": "patients",
    "case_id": "cases",
    "case_arch_id": "arches",
    "dental_lab_id": "labs",
    "prosthesis_id": "prostheses",
    "coverage_id": "coverages",
    "warranty_claim_id": "warranty_claims",
    "post_delivery_service_id": "services",
    "attributed_lab_case_id": "labcases",
    "superseded_prosthesis_id": "prostheses",
    "payment_plan_id": "plans",
}


class Ctx(object):
    __slots__ = ("user_id", "role", "body", "args")

    def __init__(self, user_id, role, body, args):
        self.user_id = user_id
        self.role = role
        self.body = body
        self.args = args


# ---------------------------------------------------------------------------
# rung 1 + rung 2
# ---------------------------------------------------------------------------
def _read_body():
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload
    return {}


def authenticate():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in pconst.ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if user_id is None or user_id == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    return Ctx(user_id, role, _read_body(), request.args)


def endpoint(roles):
    """Rung 1 (authentication) then rung 2 (role authorisation)."""
    allowed = frozenset(roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(**kw):
            ctx = authenticate()
            if ctx.role not in allowed:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            return fn(ctx, **kw)

        return wrapper

    return deco


# ---------------------------------------------------------------------------
# rung 3 -- entity-backed ownership (five endpoints, no others)
# ---------------------------------------------------------------------------
def owner_patient_guard(ctx, owning_patient_id):
    """A `Patient` caller must be the owning patient.  `owning_patient_id` is
    None when the target row does not exist, in which case rung 4 speaks."""
    if ctx.role != "Patient":
        return
    if owning_patient_id is None:
        return
    if ctx.user_id != owning_patient_id:
        raise ApiError("ERR_NOT_OWNER")


def owner_lab_guard(ctx, owning_lab_id):
    if ctx.role != "LabTechnician":
        return
    if owning_lab_id is None:
        return
    if ctx.user_id != owning_lab_id:
        raise ApiError("ERR_NOT_OWNER")


# ---------------------------------------------------------------------------
# rung 4 -- path existence
# ---------------------------------------------------------------------------
def path_row(param, value):
    collection, err = PATH_ENTITY[param]
    row = getattr(db, collection).get(value)
    if row is None:
        raise ApiError(err)
    return row


def path_row_or_none(param, value):
    collection, _ = PATH_ENTITY[param]
    return getattr(db, collection).get(value)


# ---------------------------------------------------------------------------
# rung 5 -- the global write gate
# ---------------------------------------------------------------------------
def patient_is_gated(patient):
    if patient is None:
        return False
    for plan in db.plans.values():
        if plan["patient_id"] == patient["id"] and plan["plan_status"] in (
            "DELINQUENT",
            "DEFAULTED",
        ):
            return True
    return False


def write_gate(patient):
    """Rung 5.  `patient` is None when the target patient cannot be reached
    yet (an unresolved body FK, say), in which case a lower rung speaks."""
    if patient_is_gated(patient):
        raise ApiError("ERR_ACCOUNT_DELINQUENT")


# ---------------------------------------------------------------------------
# rung 6 -- body foreign keys
# ---------------------------------------------------------------------------
def body_fks(ctx, fields):
    """Validate the listed body FKs, in the order given.  Absent or null
    values are skipped -- a missing required FK belongs to rung 7."""
    resolved = {}
    for field in fields:
        if field not in ctx.body:
            continue
        value = ctx.body[field]
        if value is None:
            continue
        collection = BODY_FK[field]
        row = None
        if isinstance(value, str):
            row = getattr(db, collection).get(value)
        if row is None:
            raise ApiError("ERR_REFERENCE_NOT_FOUND")
        resolved[field] = row
    return resolved


def fk_row(ctx, field):
    value = ctx.body.get(field)
    if value is None:
        return None
    return getattr(db, BODY_FK[field]).get(value)


# ---------------------------------------------------------------------------
# rung 7 -- request schema and ranges
# ---------------------------------------------------------------------------
def bad_request(message="The request failed schema or range validation."):
    raise ApiError("ERR_VALIDATION", message)


def require_present(ctx, *fields):
    for field in fields:
        if field not in ctx.body or ctx.body[field] is None:
            bad_request("Required field '%s' is missing." % field)


def require_string(ctx, *fields):
    require_present(ctx, *fields)
    for field in fields:
        if not isinstance(ctx.body[field], str):
            bad_request("Field '%s' must be a string." % field)


def as_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    return None


def require_int(ctx, field, minimum=None, maximum=None):
    require_present(ctx, field)
    value = as_int(ctx.body[field])
    if value is None:
        bad_request("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        bad_request("Field '%s' is below its declared minimum." % field)
    if maximum is not None and value > maximum:
        bad_request("Field '%s' is above its declared maximum." % field)
    return value


def optional_int(ctx, field, default, minimum=None, maximum=None):
    if field not in ctx.body or ctx.body[field] is None:
        return default
    return require_int(ctx, field, minimum, maximum)


def require_number(ctx, field):
    require_present(ctx, field)
    value = to_decimal(ctx.body[field])
    if value is None:
        bad_request("Field '%s' must be a number." % field)
    return value


def optional_number(ctx, field, default):
    if field not in ctx.body or ctx.body[field] is None:
        return default
    return require_number(ctx, field)


def optional_bool(ctx, field, default):
    if field not in ctx.body or ctx.body[field] is None:
        return default
    value = ctx.body[field]
    if not isinstance(value, bool):
        bad_request("Field '%s' must be a boolean." % field)
    return value


def require_instant(ctx, field):
    require_present(ctx, field)
    value = parse_instant(ctx.body[field])
    if value is None:
        bad_request("Field '%s' must be an ISO 8601 instant." % field)
    return value


def require_enum_value(ctx, field):
    """Rung 7 half of an enum field: it must be present and a string.
    Membership is rung 8."""
    require_present(ctx, field)
    if not isinstance(ctx.body[field], str):
        bad_request("Field '%s' must be a string." % field)
    return ctx.body[field]


# ---------------------------------------------------------------------------
# rung 8 -- enum membership, exhaustively routed
#
# ONLY the fields listed by PRD rung 8 route here.  Every other enum-membership
# failure -- including every enum-valued query filter and every server-computed
# enum -- routes to ERR_VALIDATION at rung 7.
# ---------------------------------------------------------------------------
INVALID_ENUM_FIELDS = frozenset(
    [
        "prosthesis_type",
        "arch_position",
        "capture_method",
        "milestone_kind",
        "decision",
        "turnaround_class",
        "purpose",
        "qc_result",
        "recall_outcome",
        "service_type",
        "fault_verdict",
        "resolved_verdict",
        "reason_code",
        "rank",
        "cob_convention",
        "determination",
        "adjudication_outcome",
        "frequency",
    ]
)


def check_enum(field, value):
    """Rung 8 for one of the eighteen exhaustively routed fields."""
    assert field in INVALID_ENUM_FIELDS
    if value not in pconst.ENUMS[field]:
        raise ApiError(
            "ERR_INVALID_ENUM",
            "Field '%s' carries a value outside its declared member set." % field,
        )
    return value


# ---------------------------------------------------------------------------
# rung 9 -- optimistic concurrency
# ---------------------------------------------------------------------------
def occ(ctx, field, parent_row):
    """Rung 7 already established that the field is present and an integer."""
    expected = as_int(ctx.body[field])
    if expected != parent_row["version"]:
        raise ApiError("ERR_STALE_VERSION")


# ---------------------------------------------------------------------------
# rung 10 / rung 12 -- terminal state and from-state, both axis-scoped
# ---------------------------------------------------------------------------
def terminal_guard(row, axis):
    if row[axis] in pconst.TERMINAL[axis]:
        raise ApiError("ERR_TERMINAL_STATE")


def from_state_guard(row, axis, allowed):
    if row[axis] not in allowed:
        raise ApiError("ERR_INVALID_STATE")


# ---------------------------------------------------------------------------
# pagination and list filters (rung 7)
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
        limit = pconst.PAGE_LIMIT_DEFAULT
    elif limit < pconst.PAGE_LIMIT_MIN or limit > pconst.PAGE_LIMIT_MAX:
        bad_request("Query parameter 'limit' is out of bounds.")
    if offset is None:
        offset = pconst.PAGE_OFFSET_DEFAULT
    elif offset < 0:
        bad_request("Query parameter 'offset' is out of bounds.")
    return limit, offset


def filter_value(ctx, name, members=None):
    """Read one query filter.  An enum-valued filter carrying a value outside
    its member set is a rung 7 failure (ERR_VALIDATION), never rung 8."""
    raw = ctx.args.get(name)
    if raw is None or raw == "":
        return None
    if members is not None and raw not in members:
        bad_request("Query parameter '%s' carries an unknown value." % name)
    return raw


def status_members(name):
    return pconst.STATUS_ENUMS.get(name) or pconst.ENUMS.get(name)


def apply_filters(rows, ctx, spec):
    """spec: list of (query_param, row_field, members_or_None)."""
    for param, field, members in spec:
        value = filter_value(ctx, param, members)
        if value is None:
            continue
        rows = [r for r in rows if r.get(field) == value]
    return rows


def paginate(rows, limit, offset):
    return rows[offset : offset + limit]
