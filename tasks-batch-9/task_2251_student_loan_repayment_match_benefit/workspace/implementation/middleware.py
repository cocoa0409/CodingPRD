"""Authentication, role authorization (PRD 2.1) and request well-formedness
(PRD 2.10 ordinal 3)."""

from flask import g, request

from errors import fail

ROLES = (
    "BenefitsAdministrator",
    "Employee",
    "PayrollOperator",
    "Recordkeeper",
    "ComplianceAuditor",
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    role = str(role).strip()
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "unknown role %r" % role)
    g.user_id = str(user_id).strip()
    g.role = role
    return g.user_id, role


def auth(*allowed_roles):
    """Ordinal 1 then ordinal 2."""
    user_id, role = authenticate()
    allowed = []
    for item in allowed_roles:
        if isinstance(item, (list, tuple, set)):
            allowed.extend(item)
        else:
            allowed.append(item)
    if role not in allowed:
        fail("ERR_FORBIDDEN_ROLE",
             "role %s may not perform this operation" % role)
    return user_id, role


# --------------------------------------------------------------------------
# body parsing / field validation -- every failure is ERR_INVALID_REQUEST
# --------------------------------------------------------------------------

def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return payload


def _present(payload, field):
    return field in payload and payload[field] is not None


def req_str(payload, field):
    if not _present(payload, field):
        fail("ERR_INVALID_REQUEST", "%s is required" % field)
    value = payload[field]
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string" % field)
    return value


def opt_str(payload, field, default=None):
    if not _present(payload, field):
        return default
    value = payload[field]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % field)
    return value


def req_int(payload, field, minimum=None, maximum=None):
    if not _present(payload, field):
        fail("ERR_INVALID_REQUEST", "%s is required" % field)
    return _as_int(payload[field], field, minimum, maximum)


def opt_int(payload, field, default=None, minimum=None, maximum=None):
    if not _present(payload, field):
        return default
    return _as_int(payload[field], field, minimum, maximum)


def _as_int(value, field, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (field, maximum))
    return value


def opt_number(payload, field, default=None, minimum=None):
    if not _present(payload, field):
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number" % field)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (field, minimum))
    return value


def opt_bool(payload, field, default=None):
    if not _present(payload, field):
        return default
    value = payload[field]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % field)
    return value


def req_enum(payload, field, members):
    value = req_str(payload, field)
    if value not in members:
        fail("ERR_INVALID_REQUEST",
             "%s must be one of %s" % (field, ", ".join(members)))
    return value


def opt_enum(payload, field, members, default=None):
    if not _present(payload, field):
        return default
    value = opt_str(payload, field)
    if value not in members:
        fail("ERR_INVALID_REQUEST",
             "%s must be one of %s" % (field, ", ".join(members)))
    return value


def req_ts(payload, field):
    import db as _db
    value = req_str(payload, field)
    parsed = _db.parse_ts(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 instant" % field)
    return value, parsed


def opt_ts(payload, field):
    import db as _db
    if not _present(payload, field):
        return None, None
    value = opt_str(payload, field)
    parsed = _db.parse_ts(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 instant" % field)
    return value, parsed
