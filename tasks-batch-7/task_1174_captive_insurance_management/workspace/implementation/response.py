"""Response envelope helpers per PRD section 2.2 / 2.3."""
from __future__ import annotations

import secrets
import string

from flask import jsonify

from clock import now_iso

_ALPHANUM = string.ascii_letters + string.digits

# Internal bookkeeping keys never serialized to clients.
_INTERNAL_FIELDS = {"created_by", "minutes_drafted_by"}
# CollateralPosting carries denormalized parent FKs internally (used by ledger
# scans); they are not part of its published schema.
_COLLATERAL_INTERNAL = {"program_id", "captive_id"}


def _scrub(obj):
    if isinstance(obj, list):
        return [_scrub(o) for o in obj]
    if isinstance(obj, dict):
        out = {}
        is_collateral = "fronting_arrangement_id" in obj and "verification_status" in obj
        for k, v in obj.items():
            if k in _INTERNAL_FIELDS:
                continue
            if is_collateral and k in _COLLATERAL_INTERNAL:
                continue
            out[k] = _scrub(v)
        return out
    return obj


def request_id() -> str:
    return "req_" + "".join(secrets.choice(_ALPHANUM) for _ in range(20))


def meta(extra=None) -> dict:
    m = {
        "api_request_id": request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, code: int = 200, pagination: dict | None = None):
    body = {
        "meta": meta(pagination),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": _scrub(data),
    }
    return jsonify(body), code


def error(error_id: str, message: str, http_status: int):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def paginate(items: list, args) -> tuple[list, dict]:
    """Apply limit/offset per PRD 2.3 (defaults 10/0, min 1, max 100).

    Returns (page_items, pagination_meta).
    """
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta_fields = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta_fields
