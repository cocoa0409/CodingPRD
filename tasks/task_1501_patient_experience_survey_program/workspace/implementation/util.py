"""Shared request-validation, datetime, rounding, and pagination helpers."""

from __future__ import annotations

from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3: limit default 10, min 1, max 100; offset default 0)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination() -> tuple[int, int]:
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise_err(
                ERR_INVALID_REQUEST,
                f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}",
            )

    if raw_offset is None or raw_offset == "":
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")

    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple[list, int]:
    total = len(items)
    return items[offset : offset + limit], total


def sort_created(items: list) -> list:
    """Sort by created_at ascending; _seq breaks identical-clock ties."""
    return sorted(items, key=lambda it: (it.get("created_at", ""), it.get("_seq", 0)))


def query_arg(name: str):
    """Query-string filter value; None when absent or empty."""
    value = request.args.get(name)
    return value if value not in (None, "") else None


# ---------------------------------------------------------------------------
# Body field validation
# ---------------------------------------------------------------------------

def get_json_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def reject_unknown_fields(body: dict, allowed: set[str]) -> None:
    for key in body:
        if key not in allowed:
            raise_err(ERR_INVALID_REQUEST, f"Unknown field: {key}")


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool))


def require_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    return body[name]


def optional_field(body: dict, name: str, default=None):
    if name not in body or body[name] is None:
        return default
    return body[name]


def require_string(body: dict, name: str) -> str:
    value = require_field(body, name)
    if not isinstance(value, str) or value == "":
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return value


def require_int(body: dict, name: str, minimum: int | None = None,
                maximum: int | None = None) -> int:
    value = require_field(body, name)
    if not is_int(value):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if minimum is not None and value < minimum:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be <= {maximum}")
    return value


def require_bool(body: dict, name: str) -> bool:
    value = require_field(body, name)
    if not isinstance(value, bool):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return value


def require_enum(body: dict, name: str, allowed: set[str]) -> str:
    value = require_field(body, name)
    if not isinstance(value, str) or value not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}")
    return value


def require_score(body: dict, name: str) -> int:
    """Composite score: integer in 1..4 (PRD 2.6 tier 5: scores within 1 to 4)."""
    return require_int(body, name, minimum=1, maximum=4)


def require_id_list(body: dict, name: str, minimum: int = 1,
                    maximum: int = 500) -> list:
    value = require_field(body, name)
    if not isinstance(value, list):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an array")
    if not (minimum <= len(value) <= maximum):
        raise_err(
            ERR_INVALID_REQUEST,
            f"Field {name} must contain between {minimum} and {maximum} entries",
        )
    for el in value:
        if not isinstance(el, str) or el == "":
            raise_err(ERR_INVALID_REQUEST, f"Field {name} must contain string ids")
    return value


def require_target_score(body: dict, name: str):
    """target_score: number 0..100 with at most two decimal places (PRD 3.8)."""
    value = require_field(body, name)
    if not is_number(value):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a number")
    dec = Decimal(str(value))
    if dec < Decimal("0") or dec > Decimal("100"):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be between 0 and 100")
    if -dec.as_tuple().exponent > 2:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must have at most 2 decimal places")
    return value


# ---------------------------------------------------------------------------
# ISO 8601 dates and datetimes
# ---------------------------------------------------------------------------

def parse_iso_date(value, field_name: str = "date") -> date:
    if not isinstance(value, str) or value == "":
        raise_err(ERR_INVALID_REQUEST, f"Field {field_name} must be an ISO 8601 date")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"Field {field_name} must be a valid ISO 8601 date")


def require_date(body: dict, name: str) -> str:
    value = require_field(body, name)
    parse_iso_date(value, name)
    return value


def parse_iso8601(value, field_name: str = "timestamp") -> datetime:
    """Parse an ISO 8601 timestamp to an aware UTC datetime for comparison."""
    if not isinstance(value, str) or value == "":
        raise_err(ERR_INVALID_REQUEST, f"Field {field_name} must be an ISO 8601 timestamp")
    text = value.strip()
    try:
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(text)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"Field {field_name} must be a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_date(clock_raw: str) -> date:
    return parse_iso8601(clock_raw, "clock").date()


# ---------------------------------------------------------------------------
# Rounding (PRD 2.9: half-up; 2dp percentages, 4dp mode shares)
# ---------------------------------------------------------------------------

def round_half_up(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def pct2(value: Decimal) -> float:
    """Two-decimal half-up percentage as a JSON float."""
    return float(round_half_up(value, 2))


def share4(value: Decimal) -> float:
    """Four-decimal half-up share delta as a JSON float."""
    return float(round_half_up(value, 4))


# ---------------------------------------------------------------------------
# Reference resolution
# ---------------------------------------------------------------------------

def get_or_404(store: dict, entity_id, label: str) -> dict:
    if not isinstance(entity_id, str) or entity_id not in store:
        raise_err(ERR_NOT_FOUND, f"{label} not found: {entity_id}")
    return store[entity_id]
