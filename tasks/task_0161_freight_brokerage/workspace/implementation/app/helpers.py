"""Shared request-parsing, validation, and lookup helpers."""

from __future__ import annotations

from typing import Any, Optional

from flask import g, request

from .errors import (
    ApiError,
    ERR_BROKERAGE_NOT_FOUND,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_REQUEST,
    ERR_STALE_DATA,
)
from .store import store
from .timeutil import parse_iso


# ---------------------------------------------------------------------------
# Body / query helpers
# ---------------------------------------------------------------------------
def get_body() -> dict:
    """Return JSON body as dict; tolerate empty body (returns ``{}``)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Malformed JSON: {exc}")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object.")
    return body


def require_field(body: dict, key: str, type_: type | tuple, *, allow_empty: bool = False):
    if key not in body or body[key] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field: {key}")
    value = body[key]
    if not isinstance(value, type_):
        # Accept ints presented as bools? bool is subclass of int — reject bools where ints expected
        if type_ is int and isinstance(value, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{key}' must be {type_}.")
        if type_ is int and isinstance(value, int) and not isinstance(value, bool):
            pass
        else:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{key}' must be {type_}.")
    if not allow_empty and isinstance(value, str) and not value.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{key}' must not be empty.")
    return value


def optional_field(body: dict, key: str, type_: type | tuple, default=None):
    if key not in body or body[key] is None:
        return default
    value = body[key]
    if type_ is int and isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{key}' must be {type_}.")
    if not isinstance(value, type_):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{key}' must be {type_}.")
    return value


def require_iso(body: dict, key: str):
    raw = require_field(body, key, str)
    try:
        return parse_iso(raw)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{key}' must be ISO 8601: {exc}")


def optional_iso(body: dict, key: str):
    if key not in body or body[key] is None:
        return None
    raw = body[key]
    if not isinstance(raw, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{key}' must be a string.")
    try:
        return parse_iso(raw)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{key}' must be ISO 8601: {exc}")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def parse_pagination():
    """Parse ``limit`` and ``offset`` query parameters per PRD §2.3."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer.")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be non-negative.")
    return limit, offset


def paginate(rows: list[dict], limit: int, offset: int):
    """Sort by created_at ascending then slice."""
    sorted_rows = sorted(rows, key=lambda r: r.get("created_at") or "")
    total_count = len(sorted_rows)
    page = sorted_rows[offset : offset + limit]
    has_more = (offset + limit) < total_count
    return page, total_count, has_more


# ---------------------------------------------------------------------------
# Path-segment resolvers
# ---------------------------------------------------------------------------
def get_brokerage_or_404(brokerage_id: str) -> dict:
    bk = store.brokerages.get(brokerage_id)
    if bk is None:
        raise ApiError(ERR_BROKERAGE_NOT_FOUND, 404, "Brokerage not found.")
    return bk


def get_scoped(map_: dict[str, dict], key: Optional[str], brokerage_id: str, err: str):
    """Return ``map_[key]`` iff it exists and its ``brokerage_id`` matches.

    Otherwise raise the given ``NOT_FOUND`` error.  A cross-brokerage match is
    treated as not found per PRD §2.8.
    """
    if key is None:
        raise ApiError(err, 404, "Not found.")
    row = map_.get(key)
    if row is None:
        raise ApiError(err, 404, "Not found.")
    if row.get("brokerage_id") != brokerage_id:
        raise ApiError(err, 404, "Not found.")
    return row


# ---------------------------------------------------------------------------
# Ownership / scoping
# ---------------------------------------------------------------------------
def ensure_shipper_self_access(shipper_id: str) -> None:
    """For ShipperUser callers, ensure X-User-ID == shipper_id."""
    if g.user_role == "ShipperUser" and g.user_id != shipper_id:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "ShipperUser can only act on their own shipper.",
        )


def ensure_carrier_self_access(carrier_id: str) -> None:
    if g.user_role == "CarrierUser" and g.user_id != carrier_id:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "CarrierUser can only act on their own carrier.",
        )


# ---------------------------------------------------------------------------
# Optimistic concurrency control
# ---------------------------------------------------------------------------
def check_version(entity: dict, body: dict) -> None:
    """If the body carries a ``version`` field, compare it to the stored version.

    Mismatch → ``ERR_STALE_DATA`` (HTTP 409).  Per PRD §2.4 the entity must be
    version-bearing; Invoice/FactoringAdvance don't carry a version and the
    check is silently skipped if absent.
    """
    if "version" not in body or body["version"] is None:
        return
    stored = entity.get("version")
    if stored is None:
        return
    supplied = body["version"]
    if not isinstance(supplied, int) or isinstance(supplied, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "version must be an integer.")
    if int(supplied) != int(stored):
        raise ApiError(ERR_STALE_DATA, 409, "Stale version supplied.")
