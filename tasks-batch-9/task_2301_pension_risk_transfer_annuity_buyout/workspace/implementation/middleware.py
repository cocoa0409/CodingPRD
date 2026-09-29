"""Auth header extraction, role checking, request-shape helpers (PRD 2.1, 2.4, 2.10)."""

import re

from flask import request

from db import db, parse_datetime
from errors import api_error
from response import (
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    PAGE_LIMIT_MIN,
    PAGE_OFFSET_DEFAULT,
)

ROLES = (
    "PlanSponsor",
    "PlanFiduciary",
    "Actuary",
    "PlanAdministrator",
    "Regulator",
    "InsurerRep",
    "Participant",
    "IndependentExpertUser",
)

ALL_ROLES = list(ROLES)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

_INT_RE = re.compile(r"^[+-]?\d+$")


def authenticate(allowed_roles):
    """Priority 1 (header auth) then priority 2 (role auth)."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or not str(user_id).strip():
        raise api_error("ERR_UNAUTHENTICATED")
    if role is None or not str(role).strip():
        raise api_error("ERR_UNAUTHENTICATED")
    user_id = str(user_id).strip()
    role = str(role).strip()
    if role not in ROLES:
        raise api_error("ERR_UNAUTHENTICATED")
    if allowed_roles is not None and role not in allowed_roles:
        raise api_error("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise api_error("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


# --------------------------------------------------------------------------
# shape helpers (priority 6 — ERR_INVALID_REQUEST)
# --------------------------------------------------------------------------


def _missing(name):
    return api_error("ERR_INVALID_REQUEST", "Field '%s' is required." % name)


def _bad(name):
    return api_error("ERR_INVALID_REQUEST", "Field '%s' is malformed." % name)


def get_string(payload, name, required=True, allow_empty=False, default=None):
    if name not in payload or payload.get(name) is None:
        if required:
            raise _missing(name)
        return default
    value = payload.get(name)
    if not isinstance(value, str):
        raise _bad(name)
    if not allow_empty and not value.strip():
        raise _bad(name)
    return value


def get_int(payload, name, required=True, default=None):
    if name not in payload or payload.get(name) is None:
        if required:
            raise _missing(name)
        return default
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad(name)
    return value


def get_bool(payload, name, required=False, default=None):
    if name not in payload or payload.get(name) is None:
        if required:
            raise _missing(name)
        return default
    value = payload.get(name)
    if not isinstance(value, bool):
        raise _bad(name)
    return value


def get_enum(payload, name, allowed, required=True, default=None):
    value = get_string(payload, name, required=required, default=None)
    if value is None:
        return default
    if value not in allowed:
        raise _bad(name)
    return value


def get_datetime(payload, name, required=True, default=None):
    if name not in payload or payload.get(name) is None:
        if required:
            raise _missing(name)
        return default
    value = payload.get(name)
    if not isinstance(value, str):
        raise _bad(name)
    parsed = parse_datetime(value)
    if parsed is None:
        raise _bad(name)
    return parsed


def require_range(value, name, low, high):
    """Priority 7 — numeric range violations surface as ERR_INVALID_AMOUNT."""
    if value is None:
        return value
    if low is not None and value < low:
        raise api_error("ERR_INVALID_AMOUNT", "Field '%s' is out of range." % name)
    if high is not None and value > high:
        raise api_error("ERR_INVALID_AMOUNT", "Field '%s' is out of range." % name)
    return value


def require_non_negative(value, name):
    return require_range(value, name, 0, None)


# --------------------------------------------------------------------------
# pagination (priority 35 — evaluated last)
# --------------------------------------------------------------------------


def pagination():
    args = request.args
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        if raw is None or not _INT_RE.match(str(raw).strip()):
            raise api_error("ERR_INVALID_PAGINATION")
        limit = int(str(raw).strip())
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise api_error("ERR_INVALID_PAGINATION")
    if "offset" in args:
        raw = args.get("offset")
        if raw is None or not _INT_RE.match(str(raw).strip()):
            raise api_error("ERR_INVALID_PAGINATION")
        offset = int(str(raw).strip())
        if offset < 0:
            raise api_error("ERR_INVALID_PAGINATION")
    return limit, offset


def slice_page(records, limit, offset):
    total = len(records)
    return records[offset : offset + limit], total


# --------------------------------------------------------------------------
# path / filter existence (priorities 4 and 5)
# --------------------------------------------------------------------------

_NOT_FOUND = {
    "plans": "ERR_PLAN_NOT_FOUND",
    "strategies": "ERR_STRATEGY_NOT_FOUND",
    "participants": "ERR_PARTICIPANT_NOT_FOUND",
    "audits": "ERR_AUDIT_NOT_FOUND",
    "windows": "ERR_WINDOW_NOT_FOUND",
    "elections": "ERR_ELECTION_NOT_FOUND",
    "tranches": "ERR_TRANCHE_NOT_FOUND",
    "insurers": "ERR_INSURER_NOT_FOUND",
    "quotes": "ERR_QUOTE_NOT_FOUND",
    "experts": "ERR_EXPERT_NOT_FOUND",
    "transfers": "ERR_TRANSFER_NOT_FOUND",
    "entries": "ERR_SETTLEMENT_ENTRY_NOT_FOUND",
    "complaints": "ERR_COMPLAINT_NOT_FOUND",
}


def lookup(collection, identifier):
    store = getattr(db, collection)
    record = store.get(identifier) if isinstance(identifier, str) else None
    if record is None:
        raise api_error(_NOT_FOUND[collection])
    return record


def filter_arg(collection, name):
    """Return (present, value). A filter naming a non-existent id 404s."""
    if name not in request.args:
        return None
    value = request.args.get(name)
    lookup(collection, value)
    return value
