"""Field-level validators (body shape checks). All raise ERR_VALIDATION_FAILED."""
import re

from errors import raise_error
from clock import parse_iso


EMPLOYEE_NO_RE = re.compile(r"^E\d{6}$")
IATA_RE = re.compile(r"^[A-Z]{3}$")
RANKS = {"CAPTAIN", "FIRST_OFFICER", "PURSER", "FLIGHT_ATTENDANT"}
ASSIGN_SOURCES = {"BID_AWARD", "RESERVE_CALLOUT", "TRADE", "ADMIN_OVERRIDE"}
LEG_TYPES = {"REVENUE", "DEADHEAD"}


def require_dict(body):
    if body is None or not isinstance(body, dict):
        raise_error("ERR_VALIDATION_FAILED", "Request body must be a JSON object.")


def require_fields(body, *names):
    for n in names:
        if n not in body or body[n] is None:
            raise_error("ERR_VALIDATION_FAILED", f"Missing required field: {n}")


def require_string(body, name, allow_empty=False):
    v = body.get(name)
    if not isinstance(v, str):
        raise_error("ERR_VALIDATION_FAILED", f"Field {name} must be a string.")
    if not allow_empty and v == "":
        raise_error("ERR_VALIDATION_FAILED", f"Field {name} must be non-empty.")
    return v


def require_int(body, name, min_value=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error("ERR_VALIDATION_FAILED", f"Field {name} must be an integer.")
    if min_value is not None and v < min_value:
        raise_error("ERR_VALIDATION_FAILED", f"Field {name} must be >= {min_value}.")
    return v


def require_iata(value, field):
    if not isinstance(value, str) or not IATA_RE.match(value):
        raise_error("ERR_VALIDATION_FAILED", f"{field} must be a 3-letter IATA code.")
    return value


def require_employee_no(value):
    if not isinstance(value, str) or not EMPLOYEE_NO_RE.match(value):
        raise_error("ERR_VALIDATION_FAILED",
                    "employee_no must match pattern E followed by 6 digits.")
    return value


def require_rank(value, field="rank"):
    if value not in RANKS:
        raise_error("ERR_VALIDATION_FAILED", f"{field} must be one of {sorted(RANKS)}.")
    return value


def require_leg_type(value):
    if value not in LEG_TYPES:
        raise_error("ERR_VALIDATION_FAILED", f"leg_type must be one of {sorted(LEG_TYPES)}.")
    return value


def parse_dt(value, field):
    if not isinstance(value, str):
        raise_error("ERR_VALIDATION_FAILED", f"{field} must be an ISO 8601 string.")
    try:
        return parse_iso(value)
    except ValueError:
        raise_error("ERR_VALIDATION_FAILED", f"{field} is not a valid ISO 8601 timestamp.")


def parse_pagination(args):
    """Parse limit/offset; raise ERR_VALIDATION_FAILED on bad values."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        raise_error("ERR_VALIDATION_FAILED", "limit must be an integer.")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise_error("ERR_VALIDATION_FAILED", "offset must be an integer.")
    if limit < 1 or limit > 100:
        raise_error("ERR_VALIDATION_FAILED", "limit must be between 1 and 100.")
    if offset < 0:
        raise_error("ERR_VALIDATION_FAILED", "offset must be >= 0.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    slice_ = rows[offset:offset + limit]
    return slice_, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
