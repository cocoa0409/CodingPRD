"""Time parsing, body validation, and pagination helpers."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from flask import request

from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_ENUM_VALUE,
    HTTP_STATUS,
)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_datetime(value: str) -> datetime | None:
    """Parse an ISO-8601 datetime (Z or offset). Returns None on failure."""
    if not isinstance(value, str):
        return None
    try:
        v = value.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def parse_date(value: str) -> date | None:
    """Parse an ISO-8601 calendar date YYYY-MM-DD. Returns None on failure."""
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def fmt_dt(dt: datetime) -> str:
    """Serialize a datetime as ISO-8601 UTC seconds with trailing Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_after(d: date) -> datetime:
    """Midnight UTC at the start of the day after date d."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(days=1)


def add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 on non-leap target years
        return d.replace(year=d.year + years, day=28)


# ---------------------------------------------------------------------------
# Body validation helpers
# ---------------------------------------------------------------------------

def get_body() -> dict:
    """Return the JSON request body as a dict; {} when empty.

    Malformed JSON or a non-object body -> ERR_INVALID_REQUEST (400).
    """
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        import json
        parsed = json.loads(raw)
    except Exception:
        raise ApiError(
            ERR_INVALID_REQUEST, HTTP_STATUS[ERR_INVALID_REQUEST],
            "Request body is not valid JSON",
        )
    if not isinstance(parsed, dict):
        raise ApiError(
            ERR_INVALID_REQUEST, HTTP_STATUS[ERR_INVALID_REQUEST],
            "Request body must be a JSON object",
        )
    return parsed


def _fail400(msg: str):
    raise ApiError(ERR_INVALID_REQUEST, HTTP_STATUS[ERR_INVALID_REQUEST], msg)


def req_str(body: dict, field: str) -> str:
    v = body.get(field)
    if v is None:
        _fail400(f"Missing required field: {field}")
    if not isinstance(v, str) or v == "":
        _fail400(f"Field {field} must be a non-empty string")
    return v


def opt_str(body: dict, field: str) -> str | None:
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        _fail400(f"Field {field} must be a string")
    return v


def req_int(body: dict, field: str) -> int:
    v = body.get(field)
    if v is None:
        _fail400(f"Missing required field: {field}")
    if isinstance(v, bool) or not isinstance(v, int):
        _fail400(f"Field {field} must be an integer")
    return v


def opt_int(body: dict, field: str) -> int | None:
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        _fail400(f"Field {field} must be an integer")
    return v


def req_date(body: dict, field: str) -> date:
    v = body.get(field)
    if v is None:
        _fail400(f"Missing required field: {field}")
    d = parse_date(v) if isinstance(v, str) else None
    if d is None:
        _fail400(f"Field {field} must be an ISO date YYYY-MM-DD")
    return d


def opt_date(body: dict, field: str) -> date | None:
    v = body.get(field)
    if v is None:
        return None
    d = parse_date(v) if isinstance(v, str) else None
    if d is None:
        _fail400(f"Field {field} must be an ISO date YYYY-MM-DD")
    return d


def req_enum(body: dict, field: str, allowed: set[str]) -> str:
    v = body.get(field)
    if v is None:
        _fail400(f"Missing required field: {field}")
    if not isinstance(v, str):
        _fail400(f"Field {field} must be a string")
    if v not in allowed:
        raise ApiError(
            ERR_INVALID_ENUM_VALUE, HTTP_STATUS[ERR_INVALID_ENUM_VALUE],
            f"Field {field} has value outside its declared enum set",
        )
    return v


def opt_enum(body: dict, field: str, allowed: set[str]) -> str | None:
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        _fail400(f"Field {field} must be a string")
    if v not in allowed:
        raise ApiError(
            ERR_INVALID_ENUM_VALUE, HTTP_STATUS[ERR_INVALID_ENUM_VALUE],
            f"Field {field} has value outside its declared enum set",
        )
    return v


# ---------------------------------------------------------------------------
# Optimistic concurrency helpers (PRD 2.8)
# ---------------------------------------------------------------------------

def require_occ_field(body: dict) -> int:
    """Envelope-level: expected_bank_version must be present and an integer."""
    from errors import ERR_INVALID_REQUEST as _EIR
    v = body.get("expected_bank_version")
    if v is None:
        raise ApiError(_EIR, HTTP_STATUS[_EIR], "Missing required field: expected_bank_version")
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(_EIR, HTTP_STATUS[_EIR], "expected_bank_version must be an integer")
    return v


def check_occ_matches(expected: int, bank: dict) -> None:
    """Priority 19: equality against current Bank.version."""
    from errors import ERR_STALE_VERSION as _ESV
    if expected != bank["version"]:
        raise ApiError(_ESV, HTTP_STATUS[_ESV],
                       "expected_bank_version does not match current Bank.version")


# ---------------------------------------------------------------------------
# Pagination helpers (PRD 2.3: limit default 10, min 1, max 100; offset 0)
# ---------------------------------------------------------------------------

def pagination_params() -> tuple[int, int]:
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            _fail400("Query parameter limit must be an integer")
        limit = max(1, min(100, limit))
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            _fail400("Query parameter offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def apply_filters(items: list[dict], spec: dict[str, str]) -> list[dict]:
    """Apply equality filters from query params.

    spec maps query param name -> entity field name. Boolean entity fields
    match against 'true'/'false' (case-insensitive); integer fields against
    their decimal form; everything else as string equality.
    """
    out = items
    for param, field in spec.items():
        raw = request.args.get(param)
        if raw is None:
            continue
        def _match(it, field=field, raw=raw):
            val = it.get(field)
            if isinstance(val, bool):
                return ("true" if val else "false") == raw.strip().lower()
            if val is None:
                return False
            return str(val) == raw.strip()
        out = [it for it in out if _match(it)]
    return out


def sorted_page(items: list[dict]) -> tuple[list[dict], int, int, int]:
    """Sort by created_at ascending (insertion order tiebreak) and paginate.

    Returns (page_items, limit, offset, total_count).
    """
    limit, offset = pagination_params()
    ordered = sorted(items, key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
