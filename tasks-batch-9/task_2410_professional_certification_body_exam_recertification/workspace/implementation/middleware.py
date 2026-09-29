"""Authentication, authorisation and body/schema helpers.

PRD 2.1: identity travels in `X-User-ID`, role in `X-User-Role`.  Layer 1 rejects a
missing or empty identity with ERR_UNAUTHENTICATED (401); layer 2 rejects an
absent, unrecognised, or non-admitted role with ERR_FORBIDDEN_ROLE (403).
GET /registry/verify is the only endpoint reachable with neither header.
"""

import json

from flask import request

from errors import ApiError
from util import dec, decimal_places, parse_ts

IDENTITY_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"

ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_ITEM_SPECIALIST = "ItemSpecialist"
ROLE_PSYCHOMETRICIAN = "Psychometrician"
ROLE_PANELIST = "Panelist"
ROLE_ELIGIBILITY_REVIEWER = "EligibilityReviewer"
ROLE_EXAM_OPERATIONS = "ExamOperations"
ROLE_CANDIDATE = "Candidate"
ROLE_CERTIFICANT = "Certificant"
ROLE_ETHICS_OFFICER = "EthicsOfficer"
ROLE_PUBLIC = "Public"

KNOWN_ROLES = {
    ROLE_PROGRAM_ADMIN,
    ROLE_ITEM_SPECIALIST,
    ROLE_PSYCHOMETRICIAN,
    ROLE_PANELIST,
    ROLE_ELIGIBILITY_REVIEWER,
    ROLE_EXAM_OPERATIONS,
    ROLE_CANDIDATE,
    ROLE_CERTIFICANT,
    ROLE_ETHICS_OFFICER,
    ROLE_PUBLIC,
}

EVERY_AUTHENTICATED_ROLE = [
    ROLE_PROGRAM_ADMIN,
    ROLE_ITEM_SPECIALIST,
    ROLE_PSYCHOMETRICIAN,
    ROLE_PANELIST,
    ROLE_ELIGIBILITY_REVIEWER,
    ROLE_EXAM_OPERATIONS,
    ROLE_ETHICS_OFFICER,
    ROLE_CANDIDATE,
    ROLE_CERTIFICANT,
]


class Actor:
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Validation layers 1 and 2, in that order."""
    user_id = request.headers.get(IDENTITY_HEADER)
    if user_id is None or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    role = request.headers.get(ROLE_HEADER)
    if role is None or not role.strip():
        raise ApiError("ERR_FORBIDDEN_ROLE")
    role = role.strip()
    if role not in KNOWN_ROLES or role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return Actor(user_id.strip(), role)


# ---------------------------------------------------------------------------
# Request body access
# ---------------------------------------------------------------------------

def peek_body():
    """Read the JSON body without raising.

    Returns a dict, or None when the payload is present but not a JSON object.
    Layer-4 body-reference existence checks run before layer-7 schema checks, so
    the body must be readable before it may be rejected.
    """
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        return None
    return parsed


def ensure_body(body):
    if body is None:
        raise ApiError("ERR_INVALID_REQUEST")
    return body


# ---------------------------------------------------------------------------
# Layer 7 -- schema validation.  Every failure is ERR_INVALID_REQUEST (400).
# ---------------------------------------------------------------------------

def _bad():
    raise ApiError("ERR_INVALID_REQUEST")


def present(body, name):
    return name in body and body[name] is not None


def req_str(body, name):
    if not present(body, name):
        _bad()
    value = body[name]
    if not isinstance(value, str) or not value.strip():
        _bad()
    return value


def opt_str(body, name, default=None):
    if not present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        _bad()
    return value


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        _bad()
    return value


def opt_enum(body, name, allowed, default=None):
    if not present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        _bad()
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def req_int(body, name, minimum=0, maximum=None):
    if not present(body, name):
        _bad()
    value = body[name]
    if not _is_int(value):
        _bad()
    if minimum is not None and value < minimum:
        _bad()
    if maximum is not None and value > maximum:
        _bad()
    return value


def opt_int(body, name, default=None, minimum=0, maximum=None):
    if not present(body, name):
        return default
    return req_int(body, name, minimum=minimum, maximum=maximum)


def req_num(body, name, minimum=None, exclusive_minimum=None, max_places=None):
    if not present(body, name):
        _bad()
    value = body[name]
    if not _is_num(value):
        _bad()
    quantity = dec(value)
    if minimum is not None and quantity < dec(minimum):
        _bad()
    if exclusive_minimum is not None and quantity <= dec(exclusive_minimum):
        _bad()
    if max_places is not None and decimal_places(quantity) > max_places:
        _bad()
    return quantity


def opt_num(body, name, default=None, minimum=None):
    if not present(body, name):
        return default
    return req_num(body, name, minimum=minimum)


def req_bool(body, name):
    if not present(body, name):
        _bad()
    value = body[name]
    if not isinstance(value, bool):
        _bad()
    return value


def opt_bool(body, name, default=None):
    if not present(body, name):
        return default
    value = body[name]
    if not isinstance(value, bool):
        _bad()
    return value


def req_ts(body, name):
    if not present(body, name):
        _bad()
    parsed = parse_ts(body[name])
    if parsed is None:
        _bad()
    return parsed


def req_str_list(body, name, minimum_length=0, distinct=False, allow_empty_items=False):
    if not present(body, name):
        _bad()
    value = body[name]
    if not isinstance(value, list):
        _bad()
    for entry in value:
        if not isinstance(entry, str):
            _bad()
        if not allow_empty_items and not entry.strip():
            _bad()
    if len(value) < minimum_length:
        _bad()
    if distinct and len(set(value)) != len(value):
        _bad()
    return list(value)


def opt_str_list(body, name, default=None, distinct=False):
    if not present(body, name):
        return list(default) if default is not None else []
    return req_str_list(body, name, distinct=distinct)


def must_be_absent(body, name):
    if present(body, name):
        _bad()
