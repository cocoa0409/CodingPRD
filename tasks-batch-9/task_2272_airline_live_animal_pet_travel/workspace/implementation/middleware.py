"""Auth header extraction, RBAC, request-body validation, pagination.

Implements validation ladder steps 1-6 of PRD section 2.6:
  1 ERR_MISSING_AUTH_HEADER   2 ERR_INVALID_ROLE   3 ERR_UNAUTHORIZED
  4 ERR_INVALID_REQUEST       5 ERR_INVALID_PAGINATION
  6 path identifiers resolve, left to right
"""
import json
import re

from flask import request

from db import parse_iso, store
from errors import ApiError

ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_RESERVATIONS_AGENT = "ReservationsAgent"
ROLE_ACCEPTANCE_AGENT = "AcceptanceAgent"
ROLE_VETERINARY_REVIEWER = "VeterinaryReviewer"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"

ALL_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_RESERVATIONS_AGENT,
    ROLE_ACCEPTANCE_AGENT,
    ROLE_VETERINARY_REVIEWER,
    ROLE_COMPLIANCE_OFFICER,
)

USER_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0

# path entity name -> (store table attribute, not-found error id)
PATH_ENTITIES = {
    "species": ("species", "ERR_SPECIES_NOT_FOUND"),
    "breed": ("breeds", "ERR_BREED_RESTRICTION_NOT_FOUND"),
    "dest_req": ("dest_reqs", "ERR_DESTINATION_REQUIREMENT_NOT_FOUND"),
    "container": ("containers", "ERR_CONTAINER_MODEL_NOT_FOUND"),
    "station": ("stations", "ERR_STATION_NOT_FOUND"),
    "embargo_rule": ("embargo_rules", "ERR_EMBARGO_RULE_NOT_FOUND"),
    "leg": ("legs", "ERR_FLIGHT_LEG_NOT_FOUND"),
    "reservation": ("reservations", "ERR_RESERVATION_NOT_FOUND"),
    "animal": ("animals", "ERR_ANIMAL_NOT_FOUND"),
    "segment": ("segments", "ERR_SEGMENT_NOT_FOUND"),
    "document": ("docs", "ERR_DOCUMENT_NOT_FOUND"),
    "allocation": ("allocations", "ERR_ALLOCATION_NOT_FOUND"),
    "incident": ("incidents", "ERR_INCIDENT_NOT_FOUND"),
}


class Ctx(object):
    """Per-request context handed to every route handler."""

    def __init__(self):
        self.user_id = None
        self.role = None
        self.body = {}
        self.limit = PAGINATION_LIMIT_DEFAULT
        self.offset = PAGINATION_OFFSET_DEFAULT
        self.row = None
        self.path_id = None

    def has(self, field):
        return field in self.body

    def get(self, field, default=None):
        value = self.body.get(field, default)
        return default if value is None and field not in self.body else value


# --------------------------------------------------------------------------
# 1-3 auth / rbac
# --------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get(USER_HEADER)
    role = request.headers.get(ROLE_HEADER)
    if not user_id or not role:
        raise ApiError("ERR_MISSING_AUTH_HEADER",
                       "Both %s and %s headers are required" % (USER_HEADER, ROLE_HEADER))
    if role not in ALL_ROLES:
        raise ApiError("ERR_INVALID_ROLE", "Unknown role '%s'" % role)
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not perform this operation" % role)
    return user_id, role


# --------------------------------------------------------------------------
# 4 request body validation
# --------------------------------------------------------------------------
def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def _check_scalar(name, value, spec):
    kind = spec.get("type")
    if kind == "string":
        if not isinstance(value, str):
            _bad("Field '%s' must be a string" % name)
        if "pattern" in spec and not re.match(spec["pattern"], value):
            _bad("Field '%s' has an invalid format" % name)
        if "min_length" in spec and len(value) < spec["min_length"]:
            _bad("Field '%s' is too short" % name)
        if "max_length" in spec and len(value) > spec["max_length"]:
            _bad("Field '%s' is too long" % name)
    elif kind == "enum":
        if not isinstance(value, str):
            _bad("Field '%s' must be a string" % name)
        if value not in spec["values"]:
            _bad("Field '%s' must be one of %s" % (name, ", ".join(spec["values"])))
    elif kind == "boolean":
        if not isinstance(value, bool):
            _bad("Field '%s' must be a boolean" % name)
    elif kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad("Field '%s' must be an integer" % name)
        _check_bounds(name, value, spec)
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad("Field '%s' must be a number" % name)
        _check_bounds(name, value, spec)
    elif kind == "datetime":
        if not isinstance(value, str):
            _bad("Field '%s' must be an ISO 8601 timestamp string" % name)
        try:
            parse_iso(value)
        except Exception:
            _bad("Field '%s' must be an ISO 8601 timestamp string" % name)
    elif kind == "array":
        if not isinstance(value, list):
            _bad("Field '%s' must be an array" % name)
        if len(value) < spec.get("min_items", 0):
            _bad("Field '%s' must contain at least %d member(s)"
                 % (name, spec.get("min_items", 0)))
        member = spec.get("items", {})
        for entry in value:
            _check_scalar(name, entry, member)
    else:  # pragma: no cover - defensive
        _bad("Field '%s' could not be validated" % name)


def _check_bounds(name, value, spec):
    if "gt" in spec and not value > spec["gt"]:
        _bad("Field '%s' must be greater than %s" % (name, spec["gt"]))
    if "gte" in spec and not value >= spec["gte"]:
        _bad("Field '%s' must be greater than or equal to %s" % (name, spec["gte"]))
    if "lte" in spec and not value <= spec["lte"]:
        _bad("Field '%s' must be less than or equal to %s" % (name, spec["lte"]))
    if "lt" in spec and not value < spec["lt"]:
        _bad("Field '%s' must be less than %s" % (name, spec["lt"]))


def parse_body(schema):
    raw = request.get_data()
    if raw is None or len(raw.strip()) == 0:
        payload = {}
    else:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            _bad("Request body must be valid JSON")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        _bad("Request body must be a JSON object")

    schema = schema or {}
    for key in payload:
        if key not in schema:
            _bad("Unknown field '%s'" % key)
    for name, spec in schema.items():
        if name not in payload:
            if spec.get("required"):
                _bad("Field '%s' is required" % name)
            continue
        value = payload[name]
        if value is None:
            if spec.get("nullable"):
                continue
            _bad("Field '%s' must not be null" % name)
        _check_scalar(name, value, spec)
    return payload


# --------------------------------------------------------------------------
# 5 pagination
# --------------------------------------------------------------------------
_INT_RE = re.compile(r"^-?\d+$")


def parse_pagination():
    limit = PAGINATION_LIMIT_DEFAULT
    offset = PAGINATION_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        if not _INT_RE.match(raw_limit.strip()):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer")
        limit = int(raw_limit.strip())
        if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
            raise ApiError("ERR_INVALID_PAGINATION",
                           "limit must be between %d and %d"
                           % (PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX))
    if raw_offset is not None:
        if not _INT_RE.match(raw_offset.strip()):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer")
        offset = int(raw_offset.strip())
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be zero or greater")
    return limit, offset


# --------------------------------------------------------------------------
# 6 path identifier resolution
# --------------------------------------------------------------------------
def resolve_path_entity(entity, row_id):
    table_name, error_id = PATH_ENTITIES[entity]
    table = getattr(store, table_name)
    row = table.get(row_id)
    if row is None:
        raise ApiError(error_id, "%s not found" % entity.replace("_", " "))
    return row


def resolve_fk(entity, row_id):
    """Body foreign key resolution (ladder step 7)."""
    return resolve_path_entity(entity, row_id)


# --------------------------------------------------------------------------
# route registration
# --------------------------------------------------------------------------
def register(app, rule, method, roles, schema=None, paginated=False, path_entity=None):
    def decorator(handler):
        def view(**kwargs):
            ctx = Ctx()
            ctx.user_id, ctx.role = authenticate(roles)
            if method in ("POST", "PUT", "PATCH"):
                ctx.body = parse_body(schema)
            if paginated:
                ctx.limit, ctx.offset = parse_pagination()
            ctx.path_id = kwargs.get("rid")
            if path_entity is not None and ctx.path_id is not None:
                ctx.row = resolve_path_entity(path_entity, ctx.path_id)
            return handler(ctx)

        view.__name__ = "%s_%s" % (method.lower(), re.sub(r"[^a-z_]", "_", rule.lower()))
        app.add_url_rule(rule, view_func=view, methods=[method], strict_slashes=False)
        return handler

    return decorator


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]
