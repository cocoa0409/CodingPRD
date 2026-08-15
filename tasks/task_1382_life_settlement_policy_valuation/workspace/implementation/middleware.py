"""Auth header extraction, role checks, body and pagination validation."""

from flask import request

from errors import (
    ApiError,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_INVALID_REQUEST,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_NOT_FOUND,
)
from util import parse_date, parse_dt

ROLES = [
    "PlatformAdmin",
    "Broker",
    "Underwriter",
    "CaseManager",
    "ComplianceOfficer",
    "FinanceOfficer",
    "PortfolioManager",
    "Investor",
]

# Read surface shared by all operator roles (Investor excluded).
READ_ALL = [
    "PlatformAdmin",
    "Broker",
    "Underwriter",
    "CaseManager",
    "ComplianceOfficer",
    "FinanceOfficer",
    "PortfolioManager",
]

PORTFOLIO_READERS = [
    "PlatformAdmin",
    "Underwriter",
    "CaseManager",
    "ComplianceOfficer",
    "FinanceOfficer",
    "PortfolioManager",
    "Investor",
]


def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and the role recognized",
        )
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN_FOR_ROLE,
            403,
            "Caller role is not authorized for this endpoint",
        )


def get_body():
    if request.data:
        data = request.get_json(silent=True)
        if data is None or not isinstance(data, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Malformed JSON body")
        return data
    return {}


def page_args():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid pagination parameters")
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid pagination parameters")
    return limit, offset


# ---------------------------------------------------------------------------
# Field validators (priority-4 ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------


def req(d, name):
    if name not in d or d[name] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: %s" % name)
    return d[name]


def opt(d, name, default=None):
    v = d.get(name, default)
    return default if v is None else v


def v_str(v, name):
    if not isinstance(v, str) or not v:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid string field: %s" % name)
    return v


def v_int(v, name, min_v=None, max_v=None):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid integer field: %s" % name)
    if min_v is not None and v < min_v:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field %s below minimum" % name)
    if max_v is not None and v > max_v:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field %s above maximum" % name)
    return v


def v_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid enum field: %s" % name)
    return v


def v_bool(v, name):
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid boolean field: %s" % name)
    return v


def v_date(v, name):
    try:
        return parse_date(v)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid date field: %s" % name)


def v_dt(v, name):
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid datetime field: %s" % name)


def v_str_list(v, name):
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid list field: %s" % name)
    return v


def v_debits(v, name):
    if not isinstance(v, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid list field: %s" % name)
    out = []
    for x in v:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid debit value")
        if x < 0 or x > 0.9:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Debit out of [0, 0.9]")
        out.append(x)
    return out


def lookup(table, entity_id, label):
    entity = table.get(entity_id)
    if entity is None:
        raise ApiError(ERR_NOT_FOUND, 404, "%s not found: %s" % (label, entity_id))
    return entity
