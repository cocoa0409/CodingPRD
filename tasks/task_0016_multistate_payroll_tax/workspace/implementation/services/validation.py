"""Input shape validation helpers (priority 16 — ERR_INVALID_REQUEST)."""
from errors import APIError, ERR_INVALID_REQUEST


STATE_CODES = {"CA", "NY", "TX", "WA"}
LOCALITY_CODES = {"NONE", "NYC", "SF"}
EMPLOYEE_STATUSES = {"ACTIVE", "ON_LEAVE", "TERMINATED"}
FILING_STATUSES = {"SINGLE", "MARRIED_JOINT", "HEAD_OF_HOUSEHOLD"}
PAY_TYPES = {"REGULAR", "OVERTIME", "DOUBLE", "RETRO"}
TAX_YEARS = {2025, 2026}
PAYCHECK_RUN_STATUSES = {"DRAFT", "APPROVED", "PAID", "VOID"}
PAYCHECK_STATUSES = {"PENDING", "PAID", "VOID"}
W4_STATUSES = {"DRAFT", "FILED", "SUPERSEDED"}
GARNISHMENT_ORDER_STATUSES = {"ACTIVE", "SUSPENDED", "SATISFIED", "RELEASED"}
GARNISHMENT_ORDER_TYPES = {"CHILD_SUPPORT", "IRS_LEVY", "STUDENT_LOAN", "CREDITOR"}
JURISDICTIONS = {
    "FEDERAL",
    "STATE:CA", "STATE:NY", "STATE:TX", "STATE:WA",
    "LOCAL:NYC", "LOCAL:SF",
}
TAX_TYPES = {"FED_INCOME", "FICA_EMPLOYEE", "STATE_INCOME", "LOCAL_INCOME"}
REMITTANCE_STATUSES = {"ACCRUING", "RECONCILED", "REMITTED"}


def require_dict(body):
    if not isinstance(body, dict):
        raise APIError(ERR_INVALID_REQUEST, 400, "request body must be a JSON object")
    return body


def require_str(d, key):
    v = d.get(key)
    if not isinstance(v, str) or not v:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{key} must be a non-empty string")
    return v


def require_int(d, key):
    v = d.get(key)
    if not isinstance(v, int) or isinstance(v, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{key} must be an integer")
    return v


def opt_int(d, key, default=0):
    if key not in d or d[key] is None:
        return default
    v = d[key]
    if not isinstance(v, int) or isinstance(v, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{key} must be an integer")
    return v


def opt_str(d, key, default=None):
    if key not in d or d[key] is None:
        return default
    v = d[key]
    if not isinstance(v, str):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{key} must be a string")
    return v


def require_enum(d, key, allowed):
    v = require_str(d, key)
    if v not in allowed:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{key} must be one of {sorted(allowed)}")
    return v


def opt_enum(d, key, allowed, default=None):
    if key not in d or d[key] is None:
        return default
    v = d[key]
    if not isinstance(v, str) or v not in allowed:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{key} must be one of {sorted(allowed)}")
    return v


def require_bool(d, key, default=False):
    if key not in d or d[key] is None:
        return default
    v = d[key]
    if not isinstance(v, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{key} must be a boolean")
    return v
