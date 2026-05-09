from decimal import Decimal, InvalidOperation
from errors import APIError, ERR_INVALID_INPUT, ERR_VERSION_CONFLICT
from common import parse_ts


def need_body(body) -> dict:
    if body is None:
        raise APIError(ERR_INVALID_INPUT, 400, "Request body required")
    if not isinstance(body, dict):
        raise APIError(ERR_INVALID_INPUT, 400, "Request body must be a JSON object")
    return body


def require_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise APIError(ERR_INVALID_INPUT, 400, f"Field '{name}' is required")
    return body[name]


def require_str(body: dict, name: str) -> str:
    v = require_field(body, name)
    if not isinstance(v, str) or v == "":
        raise APIError(ERR_INVALID_INPUT, 400, f"Field '{name}' must be a non-empty string")
    return v


def require_int(body: dict, name: str, *, min_value: int | None = None, max_value: int | None = None) -> int:
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_INVALID_INPUT, 400, f"Field '{name}' must be an integer")
    if min_value is not None and v < min_value:
        raise APIError(ERR_INVALID_INPUT, 400, f"Field '{name}' below minimum {min_value}")
    if max_value is not None and v > max_value:
        raise APIError(ERR_INVALID_INPUT, 400, f"Field '{name}' above maximum {max_value}")
    return v


def require_decimal(body: dict, name: str, *, min_value: Decimal | None = None, max_value: Decimal | None = None,
                    strictly_positive: bool = False) -> Decimal:
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float, str, Decimal)):
        raise APIError(ERR_INVALID_INPUT, 400, f"Field '{name}' must be numeric")
    try:
        d = Decimal(str(v)) if not isinstance(v, Decimal) else v
    except (InvalidOperation, ValueError):
        raise APIError(ERR_INVALID_INPUT, 400, f"Field '{name}' must be numeric")
    if strictly_positive and d <= 0:
        raise APIError(ERR_INVALID_INPUT, 400, f"Field '{name}' must be > 0")
    if min_value is not None and d < min_value:
        raise APIError(ERR_INVALID_INPUT, 400, f"Field '{name}' below minimum")
    if max_value is not None and d > max_value:
        raise APIError(ERR_INVALID_INPUT, 400, f"Field '{name}' above maximum")
    return d


def require_enum(body: dict, name: str, allowed: set[str]) -> str:
    v = require_str(body, name)
    if v not in allowed:
        raise APIError(ERR_INVALID_INPUT, 400, f"Field '{name}' must be one of {sorted(allowed)}")
    return v


def require_timestamp(body: dict, name: str):
    v = require_field(body, name)
    if not isinstance(v, str):
        raise APIError(ERR_INVALID_INPUT, 400, f"Field '{name}' must be an ISO 8601 timestamp string")
    try:
        return parse_ts(v)
    except ValueError:
        raise APIError(ERR_INVALID_INPUT, 400, f"Field '{name}' must be an ISO 8601 timestamp")


def optional_bool(body: dict, name: str) -> bool | None:
    if name not in body or body[name] is None:
        return None
    v = body[name]
    if not isinstance(v, bool):
        raise APIError(ERR_INVALID_INPUT, 400, f"Field '{name}' must be a boolean")
    return v


def occ_check(entity: dict, body: dict) -> None:
    """Priority 21: optimistic concurrency. If body supplies 'version', it must match."""
    if not isinstance(body, dict):
        return
    if "version" not in body or body["version"] is None:
        return
    v = body["version"]
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_INVALID_INPUT, 400, "Field 'version' must be an integer")
    if v != entity.get("version"):
        raise APIError(ERR_VERSION_CONFLICT, 409, "Version conflict")
