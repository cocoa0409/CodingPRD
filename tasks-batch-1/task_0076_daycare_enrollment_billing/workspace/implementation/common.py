"""Shared request-parsing, validation, pagination, and entity helpers."""
from __future__ import annotations

from typing import Any, Optional
from flask import request

from db import db, new_id, now_iso
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
)


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------
def get_body() -> dict:
    if request.method in ("POST", "PATCH", "PUT"):
        if request.content_length in (None, 0) and not request.data:
            return {}
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            raise APIError(ERR_INVALID_REQUEST, 400, "Malformed JSON body")
        if data is None:
            # empty body is acceptable for parameterless POSTs
            if not request.data:
                return {}
            raise APIError(ERR_INVALID_REQUEST, 400, "Malformed JSON body")
        if not isinstance(data, dict):
            raise APIError(ERR_INVALID_REQUEST, 400, "Body must be a JSON object")
        return data
    return {}


def require_field(body: dict, name: str) -> Any:
    if name not in body or body[name] is None:
        raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
    return body[name]


def require_str(body: dict, name: str) -> str:
    v = require_field(body, name)
    if not isinstance(v, str) or v == "":
        raise APIError(ERR_INVALID_REQUEST, 400, f"Field {name} must be a non-empty string")
    return v


def require_int(body: dict, name: str, minimum: Optional[int] = None,
                maximum: Optional[int] = None) -> int:
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_INVALID_REQUEST, 400, f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        raise APIError(ERR_INVALID_REQUEST, 400, f"Field {name} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise APIError(ERR_INVALID_REQUEST, 400, f"Field {name} must be <= {maximum}")
    return v


def optional_int(body: dict, name: str, default: int, minimum: Optional[int] = None,
                 maximum: Optional[int] = None) -> int:
    if name not in body or body[name] is None:
        return default
    return require_int(body, name, minimum, maximum)


def require_enum(body: dict, name: str, allowed: set) -> str:
    v = require_field(body, name)
    if not isinstance(v, str) or v not in allowed:
        raise APIError(ERR_INVALID_REQUEST, 400,
                       f"Field {name} must be one of {sorted(allowed)}")
    return v


def require_bool_optional(body: dict, name: str, default: bool) -> bool:
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, f"Field {name} must be a boolean")
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0
# ---------------------------------------------------------------------------
def parse_pagination() -> tuple[int, int]:
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise APIError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise APIError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise APIError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise APIError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple[list, int]:
    total = len(items)
    return items[offset:offset + limit], total


# ---------------------------------------------------------------------------
# Entity lifecycle helpers
# ---------------------------------------------------------------------------
def base_entity(versioned: bool = True) -> dict:
    """Common system fields (PRD §2.4). versioned=False for Payment/TaxStatement."""
    ts = now_iso()
    ent = {
        "id": new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if versioned:
        ent["updated_at"] = ts
        ent["version"] = 1
    return ent


def touch(ent: dict) -> None:
    """Mutation: bump updated_at and version."""
    ent["updated_at"] = now_iso()
    ent["version"] = ent.get("version", 1) + 1


def public(ent: dict) -> dict:
    """Strip internal-only keys before serialization."""
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def get_or_404(coll: dict, rid: str, what: str = "resource") -> dict:
    ent = coll.get(rid)
    if ent is None:
        raise APIError(ERR_NOT_FOUND, 404, f"{what} not found")
    return ent
