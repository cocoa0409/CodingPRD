"""Auth header extraction, role checking, and structural input validation.

Refusal ordering follows PRD 2.10 ("Order of Refusal"):
  1  role membership              ERR_UNAUTHORIZED
  2  ownership                    ERR_NOT_PROPOSAL_OWNER / ERR_NOT_BOARD_OPERATOR /
                                  ERR_NOT_COMMITTEE_MEMBER
  3  structural ERR_VALIDATION    required -> enum -> numeric -> pagination
  4  ERR_INVALID_INTERVAL
  5  ERR_DUPLICATE_KEY / ERR_DUPLICATE_VOTE / ERR_PROGRAM_ALREADY_EXISTS
  6  existence (path left-to-right, then body foreign keys)
  7  cross-reference coherence
  8  stale-version guards
  9  ERR_SEGREGATION_OF_DUTIES
 10  ERR_PROGRAM_RESTRICTED / ERR_SELF_VOTE_FORBIDDEN / ERR_REVOCATION_UNSUPPORTED
 11  state legality
 12  actor-eligibility
 13  temporal / collision
 14  capacity / quota / threshold
"""

import re
from datetime import date, datetime, timezone

from flask import request

from errors import ApiError

ROLE_PROGRAM_DIRECTOR = "ProgramDirector"
ROLE_COMMITTEE_MEMBER = "CommitteeMember"
ROLE_VOLUNTEER = "Volunteer"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_TRAINING_COORDINATOR = "TrainingCoordinator"
ROLE_DEVELOPMENT_COORDINATOR = "DevelopmentCoordinator"

ALL_ROLES = (
    ROLE_PROGRAM_DIRECTOR,
    ROLE_COMMITTEE_MEMBER,
    ROLE_VOLUNTEER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_TRAINING_COORDINATOR,
    ROLE_DEVELOPMENT_COORDINATOR,
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate(*allowed_roles):
    """Rung 1 of the Order of Refusal."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id:
        raise ApiError("ERR_UNAUTHORIZED", "The %s header is required." % USER_ID_HEADER)
    if role not in ALL_ROLES or role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role '%s' may not invoke this endpoint." % (role or ""))
    return user_id, role


def caller_id():
    return request.headers.get(USER_ID_HEADER)


# ---------------------------------------------------------------------------
# Body access
# ---------------------------------------------------------------------------

def body():
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def invalid(message):
    raise ApiError("ERR_VALIDATION", message)


def require_present(data, *names):
    for name in names:
        if name not in data or data[name] is None:
            invalid("Field '%s' is required." % name)


def enum_field(data, name, allowed, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            invalid("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        invalid("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def int_field(data, name, minimum=None, maximum=None, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            invalid("Field '%s' is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        invalid("Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        invalid("Field '%s' must be at most %d." % (name, maximum))
    return value


def str_field(data, name, required=True, non_empty=False, default=None):
    if name not in data or data[name] is None:
        if required:
            invalid("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % name)
    if non_empty and value.strip() == "":
        invalid("Field '%s' must not be empty." % name)
    return value


def bool_field(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            invalid("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, bool):
        invalid("Field '%s' must be a boolean." % name)
    return value


def list_field(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            invalid("Field '%s' is required." % name)
        return default if default is not None else []
    value = data[name]
    if not isinstance(value, list):
        invalid("Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, str):
            invalid("Field '%s' must be an array of strings." % name)
    return list(value)


def parse_moment(text):
    if not isinstance(text, str):
        return None
    candidate = text.strip()
    if not candidate:
        return None
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def datetime_field(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            invalid("Field '%s' is required." % name)
        return default
    moment = parse_moment(data[name])
    if moment is None:
        invalid("Field '%s' must be an ISO 8601 timestamp." % name)
    return moment


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def date_field(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            invalid("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        invalid("Field '%s' must be a YYYY-MM-DD date." % name)
    try:
        parsed = datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        invalid("Field '%s' must be a YYYY-MM-DD date." % name)
    return parsed


_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2}$")


def language_field(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            invalid("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or not _LANGUAGE_RE.match(value):
        invalid("Field '%s' must be a two-letter language code." % name)
    return value


# ---------------------------------------------------------------------------
# Existence (rung 6)
# ---------------------------------------------------------------------------

def lookup(store, key, error_id):
    if not isinstance(key, str):
        raise ApiError(error_id)
    row = store.get(key)
    if row is None:
        raise ApiError(error_id)
    return row


def optional_lookup(store, key, error_id):
    if key is None:
        return None
    if not isinstance(key, str):
        raise ApiError(error_id)
    row = store.get(key)
    if row is None:
        raise ApiError(error_id)
    return row


def bool_query(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return None


def int_query(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def str_query(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
