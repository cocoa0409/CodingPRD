"""Shared helpers used across the state engines and routes."""
from __future__ import annotations

from typing import Any

from db import store
from errors import ApiError


def bump(row: dict) -> None:
    """Common-fields mutation: refresh updated_at and increment version."""
    if "version" in row:
        row["version"] = int(row["version"]) + 1
        row["updated_at"] = store.now()


def check_version(row: dict, body: dict) -> None:
    """Optimistic concurrency: when `version` is supplied in body, compare.

    Skip the check when `version` is absent (PRD §2.6).
    Raises ERR_VERSION_MISMATCH on mismatch.
    """
    if "version" not in row:
        return  # Entities without OCC (e.g., BeneficiaryDesignation).
    if not isinstance(body, dict):
        return
    if "version" not in body:
        return
    supplied = body.get("version")
    if not isinstance(supplied, int) or isinstance(supplied, bool):
        raise ApiError("ERR_BAD_REQUEST", 400, "version must be an integer.")
    if supplied != row["version"]:
        raise ApiError("ERR_VERSION_MISMATCH", 409,
                       "Supplied version does not match the current resource version.")


def require_estate(estate_id: str) -> dict:
    e = store.estates.get(estate_id)
    if not e:
        raise ApiError("ERR_NOT_FOUND", 404, "Estate not found.")
    return e


def require_child(table: dict, parent_id: str, child_id: str, parent_key: str = "estate_id") -> dict:
    row = table.get(child_id)
    if not row or row.get(parent_key) != parent_id:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found.")
    return row


def pop_pagination(args) -> tuple[int, int]:
    """Read limit / offset from request.args. Raises ERR_BAD_REQUEST on out-of-range."""
    from config import DEFAULT_LIMIT, DEFAULT_OFFSET, MAX_LIMIT, MIN_LIMIT

    def _as_int(v, default):
        if v is None or v == "":
            return default
        try:
            return int(v)
        except (TypeError, ValueError):
            raise ApiError("ERR_BAD_REQUEST", 400, "limit/offset must be integers.")

    limit = _as_int(args.get("limit"), DEFAULT_LIMIT)
    offset = _as_int(args.get("offset"), DEFAULT_OFFSET)
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise ApiError("ERR_BAD_REQUEST", 400,
                       f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}.")
    if offset < 0:
        raise ApiError("ERR_BAD_REQUEST", 400, "offset must be non-negative.")
    return limit, offset


def sort_by_created_at(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: r["created_at"])


def paginate(rows: list[dict], limit: int, offset: int) -> tuple[list[dict], int]:
    total = len(rows)
    return rows[offset: offset + limit], total


def get_json_body(request) -> dict:
    """Read and shallow-validate JSON body — empty body returns {}."""
    if request.method in ("POST", "PATCH", "PUT", "DELETE"):
        try:
            body = request.get_json(silent=True, force=True) or {}
        except Exception:
            raise ApiError("ERR_BAD_REQUEST", 400, "Malformed JSON body.")
        if not isinstance(body, dict):
            raise ApiError("ERR_BAD_REQUEST", 400, "Body must be a JSON object.")
        return body
    return {}
