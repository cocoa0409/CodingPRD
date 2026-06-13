"""Shared helpers: system fields, mutation bookkeeping, pagination, body parse.

Common resource properties (PRD §2.4):
  Every primary resource carries id, created_at, updated_at, integer version.
  version starts at 1 on create and increments by 1 on every mutation;
  updated_at refreshes on every mutation. A WalletLedgerEntry is leaner: it
  carries only id and created_at (no updated_at, no version) — append-only.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Tuple

from flask import request

from db import new_uuid, now_iso, next_seq
from errors import APIError, ERR_INVALID_REQUEST


# ---------------------------------------------------------------------------
# Money / rounding
# ---------------------------------------------------------------------------
def round_half_up(value) -> int:
    """Round a numeric value to the nearest integer cent, half up.

    Uses Decimal to avoid IEEE-754 error (never float). value may be Decimal,
    int, or a numeric Decimal-coercible string.
    """
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# System fields & mutation bookkeeping
# ---------------------------------------------------------------------------
def init_common(record: Dict[str, Any]) -> Dict[str, Any]:
    """Stamp id/created_at/updated_at/version on a brand-new primary resource."""
    ts = now_iso()
    record["id"] = new_uuid()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def init_ledger(record: Dict[str, Any]) -> Dict[str, Any]:
    """Stamp id/created_at on a WalletLedgerEntry (leaner — no version/updated_at)."""
    record["id"] = new_uuid()
    record["created_at"] = now_iso()
    record["_seq"] = next_seq()
    return record


def touch(record: Dict[str, Any]) -> None:
    """Record a mutation: bump version, refresh updated_at (PRD §2.4 / §2.8).

    A change to a derived/computed field is still a mutation of its owner.
    """
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Serialization — strip internal-only keys (those prefixed with '_')
# ---------------------------------------------------------------------------
def public(record: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in record.items() if not k.startswith("_")}


def public_list(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [public(r) for r in records]


# ---------------------------------------------------------------------------
# created_at ASC ordering (stable via internal _seq tiebreaker)
# ---------------------------------------------------------------------------
def by_created_asc(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------
def parse_pagination() -> Tuple[int, int]:
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise APIError(ERR_INVALID_REQUEST, 422, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise APIError(ERR_INVALID_REQUEST, 422, "limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise APIError(ERR_INVALID_REQUEST, 422, "offset must be an integer")
        if offset < 0:
            raise APIError(ERR_INVALID_REQUEST, 422, "offset must be >= 0")

    return limit, offset


def paginate(records: List[Dict[str, Any]], limit: int, offset: int) -> Tuple[List[Dict[str, Any]], int]:
    total = len(records)
    window = records[offset:offset + limit]
    return window, total


# ---------------------------------------------------------------------------
# Request body parsing & field validation (priority 4 — ERR_INVALID_REQUEST 422)
# ---------------------------------------------------------------------------
def get_json_body() -> Dict[str, Any]:
    """Return the JSON body as a dict; empty body -> {}. Malformed -> 422."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # No body provided at all is acceptable for no-input endpoints.
        if not request.data:
            return {}
        raise APIError(ERR_INVALID_REQUEST, 422, "Request body must be valid JSON")
    if not isinstance(data, dict):
        raise APIError(ERR_INVALID_REQUEST, 422, "Request body must be a JSON object")
    return data


def require_str(body: Dict[str, Any], field: str) -> str:
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise APIError(ERR_INVALID_REQUEST, 422, f"Field '{field}' is required and must be a non-empty string")
    return v


def require_enum(body: Dict[str, Any], field: str, allowed: set) -> str:
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise APIError(ERR_INVALID_REQUEST, 422, f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def require_int(body: Dict[str, Any], field: str, minimum: int = None) -> int:
    v = body.get(field)
    # Reject bools (bool is a subtype of int in Python) and non-ints.
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_INVALID_REQUEST, 422, f"Field '{field}' is required and must be an integer")
    if minimum is not None and v < minimum:
        raise APIError(ERR_INVALID_REQUEST, 422, f"Field '{field}' must be >= {minimum}")
    return v


def optional_int(body: Dict[str, Any], field: str, minimum: int = None) -> Any:
    if field not in body or body.get(field) is None:
        return None
    return require_int(body, field, minimum)


def optional_bool(body: Dict[str, Any], field: str, default: bool = False) -> bool:
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise APIError(ERR_INVALID_REQUEST, 422, f"Field '{field}' must be a boolean")
    return v


def optional_str(body: Dict[str, Any], field: str):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise APIError(ERR_INVALID_REQUEST, 422, f"Field '{field}' must be a string")
    return v
