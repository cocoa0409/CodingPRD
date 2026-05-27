"""Shared utilities: body parsing, FK lookups, pagination, identity-equality."""

import uuid
from flask import request

from db import db
from errors import raise_api


def new_id() -> str:
    return str(uuid.uuid4())


def get_json_body() -> dict:
    """Parse JSON body. Missing body -> empty dict. Malformed -> ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        raise_api("ERR_INVALID_REQUEST", "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_api("ERR_INVALID_REQUEST", "JSON body must be an object")
    return body


def require_str(body: dict, field: str, allow_empty: bool = False) -> str:
    v = body.get(field, None)
    if v is None:
        raise_api("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    if not isinstance(v, str):
        raise_api("ERR_INVALID_REQUEST", f"Field {field} must be a string")
    if not allow_empty and not v:
        raise_api("ERR_INVALID_REQUEST", f"Field {field} must be non-empty")
    return v


def require_nonempty_str(body: dict, field: str) -> str:
    return require_str(body, field, allow_empty=False)


def optional_str(body: dict, field: str):
    v = body.get(field, None)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_api("ERR_INVALID_REQUEST", f"Field {field} must be a string")
    return v


def require_bool(body: dict, field: str) -> bool:
    v = body.get(field, None)
    if v is None or not isinstance(v, bool):
        raise_api("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return v


def optional_bool(body: dict, field: str, default: bool = None):
    v = body.get(field, None)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise_api("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return v


def require_int(body: dict, field: str, min_value: int = None) -> int:
    v = body.get(field, None)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_api("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if min_value is not None and v < min_value:
        raise_api("ERR_INVALID_REQUEST", f"Field {field} must be >= {min_value}")
    return v


def optional_int(body: dict, field: str, default=None, min_value: int = None):
    v = body.get(field, None)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise_api("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if min_value is not None and v < min_value:
        raise_api("ERR_INVALID_REQUEST", f"Field {field} must be >= {min_value}")
    return v


def parse_pagination():
    """Parse limit/offset query params per PRD §2.3.

    Defaults: limit=10 (min 1, max 100), offset=0.
    Invalid values -> ERR_INVALID_REQUEST.
    """
    args = request.args
    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_api("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_api("ERR_INVALID_REQUEST", "limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_api("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise_api("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit, offset


def paginate(rows, limit: int, offset: int):
    """Sort by created_at ASC, then apply offset/limit. Returns (page, total_count)."""
    sorted_rows = sorted(rows, key=lambda r: r.get("created_at", ""))
    total = len(sorted_rows)
    page = sorted_rows[offset:offset + limit]
    return page, total


# --- FK lookup helpers ---

def get_household_or_parent_404(hh_id: str) -> dict:
    hh = db.households.get(hh_id)
    if hh is None:
        raise_api("ERR_PARENT_NOT_FOUND", f"Household {hh_id} not found")
    return hh


def get_member_or_parent_404(member_id: str) -> dict:
    m = db.members.get(member_id)
    if m is None:
        raise_api("ERR_PARENT_NOT_FOUND", f"HouseholdMember {member_id} not found")
    return m


def get_card_or_parent_404(card_id: str) -> dict:
    c = db.ebt_cards.get(card_id)
    if c is None:
        raise_api("ERR_PARENT_NOT_FOUND", f"EBTCard {card_id} not found")
    return c
