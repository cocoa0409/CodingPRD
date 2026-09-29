"""Authentication, role checks and payload shape validation."""

import re

from flask import request

from db import parse_dt
from errors import ApiError

ROLE_ADMIN = "NumberingAdministrator"
ROLE_APPROVER = "RegulatoryApprover"
ROLE_CARRIER = "CarrierRepresentative"
ROLE_PORTING = "PortingOperations"
ROLE_COMMENTER = "PublicCommenter"

ALL_ROLES = (ROLE_ADMIN, ROLE_APPROVER, ROLE_CARRIER, ROLE_PORTING, ROLE_COMMENTER)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    return Actor(user_id.strip(), role.strip())


def require_roles(*allowed):
    """Priority 1 then priority 2 of the validation pipeline."""
    actor = authenticate()
    if actor.role not in allowed:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "role %s may not call this endpoint" % actor.role,
        )
    return actor


def check_action_role(actor, action, mapping):
    """Priority 7: per-action role partitioning inside a shared endpoint."""
    allowed = mapping.get(action)
    if not allowed:
        return
    if actor.role not in allowed:
        raise ApiError(
            "ERR_ACTION_ROLE_MISMATCH",
            "role %s may not send %s" % (actor.role, action),
        )


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return payload


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def missing(payload, key):
    return key not in payload or payload[key] is None


def req_str(payload, key, min_len=1, max_len=None, pattern=None):
    if missing(payload, key):
        bad("%s is required" % key)
    return opt_str(payload, key, min_len, max_len, pattern)


def opt_str(payload, key, min_len=1, max_len=None, pattern=None, default=None):
    if missing(payload, key):
        return default
    value = payload[key]
    if not isinstance(value, str):
        bad("%s must be a string" % key)
    if min_len is not None and len(value) < min_len:
        bad("%s must be at least %d characters" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters" % (key, max_len))
    if pattern is not None and not re.match(pattern, value):
        bad("%s is malformed" % key)
    return value


def req_id(payload, key):
    if missing(payload, key):
        bad("%s is required" % key)
    value = payload[key]
    if not isinstance(value, str) or value.strip() == "":
        bad("%s must be a non-empty string" % key)
    return value


def opt_id(payload, key):
    if missing(payload, key):
        return None
    value = payload[key]
    if not isinstance(value, str) or value.strip() == "":
        bad("%s must be a non-empty string" % key)
    return value


def req_int(payload, key, minimum=None, maximum=None):
    if missing(payload, key):
        bad("%s is required" % key)
    return opt_int(payload, key, minimum, maximum)


def opt_int(payload, key, minimum=None, maximum=None, default=None):
    if missing(payload, key):
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer" % key)
    if minimum is not None and value < minimum:
        bad("%s must be at least %d" % (key, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be at most %d" % (key, maximum))
    return value


def req_enum(payload, key, choices):
    if missing(payload, key):
        bad("%s is required" % key)
    return opt_enum(payload, key, choices)


def opt_enum(payload, key, choices, default=None):
    if missing(payload, key):
        return default
    value = payload[key]
    if not isinstance(value, str) or value not in choices:
        bad("%s must be one of %s" % (key, ", ".join(sorted(choices))))
    return value


def req_dt(payload, key):
    if missing(payload, key):
        bad("%s is required" % key)
    return opt_dt(payload, key)


def opt_dt(payload, key, default=None):
    if missing(payload, key):
        return default
    value = payload[key]
    if not isinstance(value, str):
        bad("%s must be an ISO 8601 timestamp string" % key)
    parsed = parse_dt(value)
    if parsed is None:
        bad("%s must be an ISO 8601 timestamp string" % key)
    return parsed


def opt_bool(payload, key, default=None):
    if missing(payload, key):
        return default
    value = payload[key]
    if not isinstance(value, bool):
        bad("%s must be a boolean" % key)
    return value


def req_int_list(payload, key, length=None, minimum=None):
    if missing(payload, key):
        bad("%s is required" % key)
    return opt_int_list(payload, key, length, minimum)


def opt_int_list(payload, key, length=None, minimum=None, default=None):
    if missing(payload, key):
        return default
    value = payload[key]
    if not isinstance(value, list):
        bad("%s must be an array" % key)
    if length is not None and len(value) != length:
        bad("%s must contain exactly %d entries" % (key, length))
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            bad("%s entries must be integers" % key)
        if minimum is not None and item < minimum:
            bad("%s entries must be at least %d" % (key, minimum))
    return list(value)


def opt_str_list(payload, key, default=None):
    if missing(payload, key):
        return default
    value = payload[key]
    if not isinstance(value, list):
        bad("%s must be an array" % key)
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            bad("%s entries must be non-empty strings" % key)
    return list(value)
