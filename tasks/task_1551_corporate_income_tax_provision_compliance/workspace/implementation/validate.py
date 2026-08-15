"""Request-body access and structural (priority-11) field validators.

Structural well-formedness is deliberately the LAST validation priority
(PRD §2.6 item 11): domain errors win over malformed-body errors when both
apply. Route handlers therefore read body fields defensively for domain
checks (a missing/wrongly-typed field simply skips the domain check) and call
the req_* validators only after every domain check has passed. Undeclared
extra fields are ignored, never rejected.
"""
from flask import request

from errors import raise_error, ERR_INVALID_REQUEST
from util import is_date_str


def body_json() -> dict:
    """Parsed JSON object body; missing/unparseable/non-object bodies read as {}."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def present_int(data: dict, field: str):
    """The field's value if present and a genuine int (bools excluded), else None."""
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    return v


def req_str(data: dict, field: str) -> str:
    v = data.get(field)
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"field '{field}' is required and must be a string")
    return v


def req_nonempty_str(data: dict, field: str) -> str:
    v = data.get(field)
    if not isinstance(v, str) or not v.strip():
        raise_error(ERR_INVALID_REQUEST,
                    f"field '{field}' is required and must be a non-empty string")
    return v


def opt_str(data: dict, field: str):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"field '{field}' must be a string when present")
    return v


def req_int(data: dict, field: str) -> int:
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"field '{field}' is required and must be an integer")
    return v


def opt_int(data: dict, field: str, default):
    v = data.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"field '{field}' must be an integer when present")
    return v


def req_bool(data: dict, field: str) -> bool:
    v = data.get(field)
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"field '{field}' is required and must be a boolean")
    return v


def req_enum(data: dict, field: str, allowed) -> str:
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST,
                    f"field '{field}' must be one of {sorted(allowed)}")
    return v


def req_date(data: dict, field: str) -> str:
    """Required ISO YYYY-MM-DD string; returned trimmed (canonical) form."""
    v = data.get(field)
    if not is_date_str(v):
        raise_error(ERR_INVALID_REQUEST,
                    f"field '{field}' is required and must be a YYYY-MM-DD date string")
    return v.strip()


def opt_nullable_str(data: dict, field: str):
    """Optional nullable string field: absent or null -> None."""
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"field '{field}' must be a string or null")
    return v


def opt_nullable_id(data: dict, field: str):
    return opt_nullable_str(data, field)
