"""Common helpers for routes: pagination, body parsing, ownership checks."""
from __future__ import annotations

from typing import Optional

from flask import request

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_RESOURCE_OWNER, ERR_NOT_FOUND
import db
from middleware import current_role, current_user_id


def parse_json_body() -> dict:
    """Best-effort JSON parsing; missing/invalid body becomes {}."""
    if request.method in {"GET", "DELETE"}:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def parse_pagination():
    """Returns (limit, offset). Defaults: limit=10, offset=0. limit range [1, 100]."""
    try:
        limit_raw = request.args.get("limit")
        offset_raw = request.args.get("offset")
        limit = int(limit_raw) if limit_raw is not None else 10
        offset = int(offset_raw) if offset_raw is not None else 0
    except (ValueError, TypeError):
        raise APIError(ERR_INVALID_REQUEST, "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise APIError(ERR_INVALID_REQUEST, "limit out of range [1, 100]")
    if offset < 0:
        raise APIError(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate_sorted(items: list, limit: int, offset: int) -> tuple:
    """Slice items per limit/offset. Returns (slice, total_count)."""
    total = len(items)
    return items[offset : offset + limit], total


def must_get(store: dict, key: str, what: str):
    """Look up an entity by id; raise ERR_NOT_FOUND if missing."""
    entity = store.get(key)
    if entity is None:
        raise APIError(ERR_NOT_FOUND, f"{what} not found")
    return entity


def borrower_ownership_check(borrower_id: str) -> None:
    """If the caller is a Borrower, verify X-User-ID equals borrower_id; else allow."""
    if current_role() == "Borrower":
        if current_user_id() != borrower_id:
            raise APIError(ERR_NOT_RESOURCE_OWNER, "Borrower does not own this resource")


def borrower_owns_loan(loan_id: str) -> None:
    """Borrower-role: ensure they own the loan via its borrower_id."""
    if current_role() == "Borrower":
        loan = db.loans.get(loan_id)
        if loan is None:
            raise APIError(ERR_NOT_FOUND, "Loan not found")
        if loan["borrower_id"] != current_user_id():
            raise APIError(ERR_NOT_RESOURCE_OWNER, "Borrower does not own this loan")


def get_field(body: dict, name: str, required: bool = True, default=None):
    if name in body:
        return body[name]
    if required:
        raise APIError(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    return default
