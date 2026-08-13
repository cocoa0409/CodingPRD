"""Shared helpers: id/timestamp generation, date/timestamp parsing, rounding."""

import re
import secrets
import string
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from errors import err_validation, ApiError, ERR_INVALID_TEMPORAL


def new_id() -> str:
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    """Request id starting with 'req_' followed by random alphanumerics."""
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def now_timestamp() -> str:
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    now = datetime.now(timezone.utc)
    base = now.strftime("%Y-%m-%dT%H:%M:%S")
    ms = now.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def round_half_up(value) -> int:
    """Round a Decimal (or numeric) to integer cents, half away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value, field: str) -> date:
    """Parse an ISO YYYY-MM-DD date. Raises ERR_VALIDATION on bad shape."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise err_validation(f"Field '{field}' must be a YYYY-MM-DD date string")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise err_validation(f"Field '{field}' is not a valid calendar date")


def parse_timestamp(value, field: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime."""
    if not isinstance(value, str):
        raise err_validation(f"Field '{field}' must be an ISO 8601 timestamp string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise err_validation(f"Field '{field}' is not a valid ISO 8601 timestamp")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def temporal_error(message: str) -> ApiError:
    return ApiError(ERR_INVALID_TEMPORAL, message, 422)


# ---- Generic request-shape validation helpers (ERR_VALIDATION, 400) ----

def require_field(body: dict, field: str):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        raise err_validation(f"Missing required field '{field}'")
    return body[field]


def optional_field(body: dict, field: str, default=None):
    if not isinstance(body, dict):
        return default
    value = body.get(field, default)
    return value


def require_string(body: dict, field: str) -> str:
    value = require_field(body, field)
    if not isinstance(value, str) or value == "":
        raise err_validation(f"Field '{field}' must be a non-empty string")
    return value


def optional_string(body: dict, field: str):
    value = body.get(field) if isinstance(body, dict) else None
    if value is None:
        return None
    if not isinstance(value, str) or value == "":
        raise err_validation(f"Field '{field}' must be a non-empty string when provided")
    return value


def require_enum(body: dict, field: str, allowed) -> str:
    value = require_field(body, field)
    if not isinstance(value, str) or value not in allowed:
        raise err_validation(f"Field '{field}' must be one of {sorted(allowed)}")
    return value


def require_int(body: dict, field: str, minimum=None) -> int:
    value = require_field(body, field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise err_validation(f"Field '{field}' must be an integer")
    if minimum is not None and value < minimum:
        raise err_validation(f"Field '{field}' must be >= {minimum}")
    return value


def require_number(body: dict, field: str, minimum=None, exclusive_minimum=None) -> float:
    value = require_field(body, field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err_validation(f"Field '{field}' must be a number")
    if minimum is not None and value < minimum:
        raise err_validation(f"Field '{field}' must be >= {minimum}")
    if exclusive_minimum is not None and value <= exclusive_minimum:
        raise err_validation(f"Field '{field}' must be > {exclusive_minimum}")
    return value
