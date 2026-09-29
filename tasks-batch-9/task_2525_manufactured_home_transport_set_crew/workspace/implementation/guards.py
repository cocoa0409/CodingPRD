"""Auth, RBAC, schema validation and lookup helpers.

Implements the first rungs of the PRD section 2.10 validation priority ladder:
priority 1 (auth headers), priority 2 (role gate), priority 3 (pure shape check),
priority 4 (path existence) and priority 5 (body reference existence).
"""
import functools
import re

from flask import g, request

from errors import fail
from store import db, parse_day, parse_instant

ROLES = (
    "NetworkAdmin",
    "PlantDispatcher",
    "TransportManager",
    "PermitDesk",
    "SetCrewLead",
    "InstallationInspector",
    "ClaimsAdjuster",
)
ANY_ROLE = ROLES

_STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


# ---------------------------------------------------------------------------
# Priority 1 + 2
# ---------------------------------------------------------------------------
def authenticate():
    """Priority 1: both identity headers present and non-empty."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED")
    g.user_id = str(user_id)
    g.user_role = str(role)


def actor_id():
    return getattr(g, "user_id", None)


def actor_role():
    return getattr(g, "user_role", None)


def roles(*allowed):
    """Priority 2: role gate, evaluated before any body parsing."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            if actor_role() not in allowed:
                fail("ERR_UNAUTHORIZED")
            return view(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Priority 3 -- pure shape check, no database reads
# ---------------------------------------------------------------------------
def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool))


def _check_one(spec, value):
    kind = spec["type"]
    name = spec["name"]
    if kind == "string":
        if not isinstance(value, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
        return value
    if kind == "state_code":
        if not isinstance(value, str) or not _STATE_CODE_RE.match(value):
            fail(
                "ERR_INVALID_REQUEST",
                "Field '%s' must be exactly two uppercase letters." % name,
            )
        return value
    if kind == "integer":
        if not _is_int(value):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    elif kind == "number":
        if not _is_number(value):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    elif kind == "boolean":
        if not isinstance(value, bool):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
        return value
    elif kind == "enum":
        if not isinstance(value, str) or value not in spec["values"]:
            fail(
                "ERR_INVALID_REQUEST",
                "Field '%s' must be one of %s." % (name, ", ".join(spec["values"])),
            )
        return value
    elif kind == "date":
        if parse_day(value) is None:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a YYYY-MM-DD date." % name)
        return value
    elif kind == "datetime":
        if parse_instant(value) is None:
            fail(
                "ERR_INVALID_REQUEST",
                "Field '%s' must be an ISO 8601 UTC instant." % name,
            )
        return value
    elif kind == "state_array":
        if not isinstance(value, list) or len(value) == 0:
            fail(
                "ERR_INVALID_REQUEST",
                "Field '%s' must be a non-empty array of state codes." % name,
            )
        for item in value:
            if not isinstance(item, str) or not _STATE_CODE_RE.match(item):
                fail(
                    "ERR_INVALID_REQUEST",
                    "Field '%s' must contain two-uppercase-letter state codes." % name,
                )
        return list(value)
    elif kind == "enum_array":
        if not isinstance(value, list) or len(value) == 0:
            fail(
                "ERR_INVALID_REQUEST",
                "Field '%s' must be a non-empty array." % name,
            )
        for item in value:
            if not isinstance(item, str) or item not in spec["values"]:
                fail(
                    "ERR_INVALID_REQUEST",
                    "Field '%s' items must be one of %s."
                    % (name, ", ".join(spec["values"])),
                )
        return list(value)
    else:  # pragma: no cover - defensive
        fail("ERR_INVALID_REQUEST", "Unsupported field type for '%s'." % name)
    # numeric bounds
    if "min" in spec and value < spec["min"]:
        fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % name)
    if "max" in spec and value > spec["max"]:
        fail("ERR_INVALID_REQUEST", "Field '%s' is above its maximum." % name)
    return value


def read_body(required_body=True):
    body = request.get_json(silent=True)
    if body is None:
        raw = request.get_data(cache=True, as_text=True)
        if raw is None or raw.strip() == "":
            if required_body:
                fail("ERR_INVALID_REQUEST", "A JSON request body is required.")
            return {}
        fail("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return body


def validate(specs, required_body=None):
    """Validate the JSON body against ``specs`` and return the parsed values."""
    if required_body is None:
        required_body = any(spec.get("required") for spec in specs)
    body = read_body(required_body=required_body)
    parsed = {}
    for spec in specs:
        name = spec["name"]
        present = name in body
        value = body.get(name)
        if not present or value is None:
            if spec.get("required"):
                fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
            if present and value is None and spec.get("nullable"):
                parsed[name] = None
            continue
        parsed[name] = _check_one(spec, value)
    return parsed


# ---------------------------------------------------------------------------
# Pagination and collection filters (PRD section 2.3)
# ---------------------------------------------------------------------------
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _query_int(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if not re.match(r"^-?\d+$", raw.strip()):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    value = int(raw.strip())
    if value < minimum:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is below its minimum." % name)
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is above its maximum." % name)
    return value


def pagination():
    limit = _query_int("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _query_int("offset", OFFSET_DEFAULT, 0, None)
    return limit, offset


def filters(spec):
    """``spec`` maps query-parameter name to either None (free string) or a list
    of allowed enum values.  An out-of-enumeration value is a schema failure."""
    out = {}
    for name, allowed in spec.items():
        raw = request.args.get(name)
        if raw is None or raw == "":
            continue
        if allowed is not None and raw not in allowed:
            fail(
                "ERR_INVALID_REQUEST",
                "Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)),
            )
        out[name] = raw
    return out


def apply_filters(rows, active):
    for name, wanted in active.items():
        rows = [row for row in rows if row.get(name) == wanted]
    return rows


# ---------------------------------------------------------------------------
# Priority 4 / 5 -- existence
# ---------------------------------------------------------------------------
def lookup(table, row_id, error_id):
    row = getattr(db, table).get(row_id)
    if row is None:
        fail(error_id)
    return row


def lookup_ref(table, row_id, error_id):
    """Body reference resolution; a non-string reference is a shape failure that
    priority 3 has already screened, so anything unresolvable is a 404."""
    row = getattr(db, table).get(row_id)
    if row is None:
        fail(error_id)
    return row
