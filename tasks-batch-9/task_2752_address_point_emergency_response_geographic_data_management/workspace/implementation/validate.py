"""Auth, schema validation, pagination and foreign-key resolution helpers.

Validation precedence (PRD §2.7): authentication -> role authorisation ->
agency identity ownership -> path-entity existence -> referenced-entity
existence -> request-schema validity -> target-state legality -> expected-version
staleness -> domain business rules.
"""

import re

from flask import request

from errors import ApiError
from store import db, parse_dt

ROLES = ["SystemAdmin", "GisAnalyst", "QcCertifier", "ProvisioningOfficer",
         "PermitCoordinator", "AgencyLiaison"]
ALL_ROLES = list(ROLES)


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------
def auth(allowed_roles):
    """Return (user_id, role) after the authentication and role checks."""
    user_id = request.headers.get("X-User-ID")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    role = request.headers.get("X-User-Role")
    if role is None or role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


# ---------------------------------------------------------------------------
# body
# ---------------------------------------------------------------------------
def body():
    """Parsed JSON object body; {} when absent. Non-object bodies are invalid."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


# ---------------------------------------------------------------------------
# scalar field validators
# ---------------------------------------------------------------------------
def req_str(data, field, min_len=1, max_len=None, pattern=None, non_blank=True):
    if field not in data or data[field] is None:
        bad(field, "is required")
    return _check_str(data, field, min_len, max_len, pattern, non_blank)


def opt_str(data, field, min_len=0, max_len=None, pattern=None, default=None,
            non_blank=False):
    if field not in data or data[field] is None:
        return default
    return _check_str(data, field, min_len, max_len, pattern, non_blank)


def _check_str(data, field, min_len, max_len, pattern, non_blank):
    value = data[field]
    if not isinstance(value, str):
        bad(field, "must be a string")
    if non_blank and value.strip() == "":
        bad(field, "must not be blank")
    if min_len is not None and len(value) < min_len:
        bad(field, "is shorter than %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        bad(field, "is longer than %d characters" % max_len)
    if pattern is not None and not re.match(pattern, value):
        bad(field, "does not match the required format")
    return value


def req_int(data, field, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        bad(field, "is required")
    return _check_int(data, field, minimum, maximum)


def opt_int(data, field, minimum=None, maximum=None, default=None):
    if field not in data or data[field] is None:
        return default
    return _check_int(data, field, minimum, maximum)


def _check_int(data, field, minimum, maximum):
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        bad(field, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        bad(field, "must be <= %d" % maximum)
    return value


def req_enum(data, field, values):
    if field not in data or data[field] is None:
        bad(field, "is required")
    return _check_enum(data, field, values)


def opt_enum(data, field, values, default=None):
    if field not in data or data[field] is None:
        return default
    return _check_enum(data, field, values)


def _check_enum(data, field, values):
    value = data[field]
    if not isinstance(value, str) or value not in values:
        bad(field, "must be one of %s" % ", ".join(values))
    return value


def req_bool(data, field):
    if field not in data or data[field] is None:
        bad(field, "is required")
    return _check_bool(data, field)


def opt_bool(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return _check_bool(data, field)


def _check_bool(data, field):
    value = data[field]
    if not isinstance(value, bool):
        bad(field, "must be a boolean")
    return value


def req_dt(data, field):
    if field not in data or data[field] is None:
        bad(field, "is required")
    return _check_dt(data, field)


def opt_dt(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return _check_dt(data, field)


def _check_dt(data, field):
    value = data[field]
    if not isinstance(value, str):
        bad(field, "must be an ISO 8601 datetime string")
    parsed = parse_dt(value)
    if parsed is None:
        bad(field, "is not a valid ISO 8601 datetime")
    return parsed


def req_number(data, field, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        bad(field, "is required")
    return _check_number(data, field, minimum, maximum)


def opt_number(data, field, minimum=None, maximum=None, default=None):
    if field not in data or data[field] is None:
        return default
    return _check_number(data, field, minimum, maximum)


def _check_number(data, field, minimum, maximum):
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(field, "must be a number")
    if minimum is not None and value < minimum:
        bad(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        bad(field, "must be <= %s" % maximum)
    return value


def req_id(data, field):
    """A foreign-key style identifier: a non-empty string."""
    if field not in data or data[field] is None:
        bad(field, "is required")
    value = data[field]
    if not isinstance(value, str) or value.strip() == "":
        bad(field, "must be a non-empty string")
    return value


def opt_id(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, str) or value.strip() == "":
        bad(field, "must be a non-empty string")
    return value


def raw_ref(data, field):
    """A candidate FK value used for the referenced-existence pass.

    Existence resolution happens BEFORE schema validation, so only genuine
    non-empty strings are resolved here; anything else is left to the schema
    pass which reports ERR_INVALID_REQUEST.
    """
    value = data.get(field)
    if isinstance(value, str) and value.strip() != "":
        return value
    return None


# ---------------------------------------------------------------------------
# query parameters
# ---------------------------------------------------------------------------
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        if not re.match(r"^-?\d+$", raw_limit.strip()):
            bad("limit", "must be an integer between 1 and 100")
        limit = int(raw_limit)
        if limit < 1 or limit > 100:
            bad("limit", "must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        if not re.match(r"^-?\d+$", raw_offset.strip()):
            bad("offset", "must be a non-negative integer")
        offset = int(raw_offset)
        if offset < 0:
            bad("offset", "must be a non-negative integer")
    return limit, offset


def q_enum(field, values):
    value = request.args.get(field)
    if value is None:
        return None
    if value not in values:
        bad(field, "must be one of %s" % ", ".join(values))
    return value


def q_str(field):
    value = request.args.get(field)
    if value is None:
        return None
    return value


def q_bool(field, default=None):
    value = request.args.get(field)
    if value is None:
        return default
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad(field, "must be a boolean")


def q_int(field, minimum=None, maximum=None):
    value = request.args.get(field)
    if value is None:
        return None
    if not re.match(r"^-?\d+$", value.strip()):
        bad(field, "must be an integer")
    parsed = int(value)
    if minimum is not None and parsed < minimum:
        bad(field, "must be >= %d" % minimum)
    if maximum is not None and parsed > maximum:
        bad(field, "must be <= %d" % maximum)
    return parsed


# ---------------------------------------------------------------------------
# existence resolution
# ---------------------------------------------------------------------------
NOT_FOUND = {
    "jurisdiction": "ERR_JURISDICTION_NOT_FOUND",
    "agency": "ERR_AGENCY_NOT_FOUND",
    "cell": "ERR_COVERAGE_CELL_NOT_FOUND",
    "road": "ERR_ROAD_NOT_FOUND",
    "point": "ERR_ADDRESS_POINT_NOT_FOUND",
    "request": "ERR_REQUEST_NOT_FOUND",
    "boundary": "ERR_BOUNDARY_NOT_FOUND",
    "assignment": "ERR_CELL_ASSIGNMENT_NOT_FOUND",
    "report": "ERR_REPORT_NOT_FOUND",
    "defect": "ERR_DEFECT_NOT_FOUND",
    "package": "ERR_PACKAGE_NOT_FOUND",
    "case": "ERR_CASE_NOT_FOUND",
    "proposal": "ERR_PROPOSAL_NOT_FOUND",
}

_TABLES = {
    "jurisdiction": lambda: db.jurisdictions,
    "agency": lambda: db.agencies,
    "cell": lambda: db.cells,
    "road": lambda: db.roads,
    "point": lambda: db.points,
    "request": lambda: db.requests,
    "boundary": lambda: db.boundaries,
    "assignment": lambda: db.assignments,
    "report": lambda: db.reports,
    "defect": lambda: db.defects,
    "package": lambda: db.packages,
    "case": lambda: db.cases,
    "proposal": lambda: db.proposals,
}


def find(kind, identifier):
    """Resolve an id or raise the entity's own not-found code."""
    table = _TABLES[kind]()
    if not isinstance(identifier, str) or identifier not in table:
        raise ApiError(NOT_FOUND[kind])
    return table[identifier]


def maybe_find(kind, identifier):
    if identifier is None:
        return None
    return find(kind, identifier)


def page(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
