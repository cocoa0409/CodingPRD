"""Generic helpers: pagination, version checks, body parsing, datetime parse."""
import re
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Tuple

from flask import request

from app.errors import ApiError, err_pagination_invalid, err_version_conflict


# ----- Body parsing -----

def parse_json_body() -> Dict[str, Any]:
    """Return JSON body as a dict, or {} when absent. Never raises on missing body."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


# ----- Pagination -----

def parse_pagination() -> Tuple[int, int]:
    """Validate and return (limit, offset) per §1.4 priority-17 rule.

    limit ∈ [1, 100], default 10; offset >= 0, default 0.
    Invalid → ERR_PAGINATION_INVALID (400).
    """
    args = request.args
    limit_str = args.get("limit")
    offset_str = args.get("offset")
    try:
        limit = int(limit_str) if limit_str is not None else 10
        offset = int(offset_str) if offset_str is not None else 0
    except (TypeError, ValueError):
        raise err_pagination_invalid()
    if limit < 1 or limit > 100 or offset < 0:
        raise err_pagination_invalid()
    return limit, offset


def paginate_sorted(records: List[Dict[str, Any]], limit: int, offset: int) -> Tuple[List[Dict[str, Any]], int]:
    """Sort records by created_at ascending (oldest first) and slice."""
    sorted_records = sorted(records, key=lambda r: r.get("created_at") or "")
    total = len(sorted_records)
    sliced = sorted_records[offset:offset + limit]
    return sliced, total


# ----- OCC version check -----

def check_version_if_supplied(resource: Dict[str, Any], body: Dict[str, Any]) -> None:
    """If the caller supplied a 'version' field, compare against stored.

    Mismatch → ERR_VERSION_CONFLICT. None / absent → skip the check.
    """
    if not body:
        return
    supplied = body.get("version", None)
    if supplied is None:
        return
    if not isinstance(supplied, int):
        # Non-integer version → treat as mismatch.
        raise err_version_conflict()
    if resource.get("version") != supplied:
        raise err_version_conflict()


def bump_version_and_timestamp(resource: Dict[str, Any], now_iso: str) -> None:
    resource["updated_at"] = now_iso
    resource["version"] = int(resource.get("version", 0)) + 1


# ----- Datetime parse -----

_ISO_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


def parse_iso_datetime(raw: Any) -> datetime:
    """Parse an ISO 8601 string into a UTC-aware datetime, or raise ValueError."""
    if not isinstance(raw, str):
        raise ValueError("Expected ISO 8601 string")
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ----- Rounding -----

def round_half_up_to_cents(amount: Decimal) -> int:
    """Round a Decimal amount of cents to the nearest integer, half-up."""
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ----- Regex helpers -----

_NPI_RE = re.compile(r"^[0-9]{10}$")
_DEA_RE = re.compile(r"^[A-Z]{2}[0-9]{7}$")
_STATE_RE = re.compile(r"^[A-Z]{2}$")


def is_valid_npi(s: Any) -> bool:
    return isinstance(s, str) and bool(_NPI_RE.fullmatch(s))


def is_valid_dea(s: Any) -> bool:
    return isinstance(s, str) and bool(_DEA_RE.fullmatch(s))


def is_valid_state_code(s: Any) -> bool:
    return isinstance(s, str) and bool(_STATE_RE.fullmatch(s))
