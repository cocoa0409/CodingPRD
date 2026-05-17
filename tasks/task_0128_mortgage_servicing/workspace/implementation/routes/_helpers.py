"""Shared helpers for route modules: body parsing, pagination, ownership."""
from __future__ import annotations

from typing import Any, Iterable

from flask import g, request

from config import DEFAULT_LIMIT, DEFAULT_OFFSET, MAX_LIMIT, MIN_LIMIT
from db import store
from errors import (
    ApiError,
    err_concurrent_update,
    err_forbidden,
    err_loan_not_found,
    err_resource_not_found,
)
from utils import parse_iso


def get_json() -> dict:
    """Return the request JSON body (always a dict; tolerates empty bodies)."""
    if request.is_json:
        body = request.get_json(silent=True)
    else:
        data = request.get_data(as_text=True)
        if not data.strip():
            return {}
        try:
            import json

            body = json.loads(data)
        except Exception:
            body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        return {}
    return body


def require_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise ApiError("ERR_PAYMENT_AMOUNT_INVALID", 422, f"Missing field {name}")
    return body[name]


def parse_pagination():
    """Return (limit, offset) honouring scaffold defaults and bounds."""
    try:
        limit = int(request.args.get("limit", DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    try:
        offset = int(request.args.get("offset", DEFAULT_OFFSET))
    except (TypeError, ValueError):
        offset = DEFAULT_OFFSET
    if limit < MIN_LIMIT:
        limit = MIN_LIMIT
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items: list, limit: int, offset: int):
    return items[offset : offset + limit]


def sort_by_created_at(items: Iterable[dict]) -> list:
    return sorted(items, key=lambda x: x["created_at"])


def get_loan_or_404(loan_id: str) -> dict:
    loan = store.loans.get(loan_id)
    if loan is None:
        raise err_loan_not_found()
    return loan


def get_borrower_or_404(borrower_id: str) -> dict:
    b = store.borrowers.get(borrower_id)
    if b is None:
        raise err_resource_not_found("Borrower not found.")
    return b


def borrower_owns_loan(loan: dict, user_id: str) -> bool:
    return loan["borrower_id"] == user_id


def enforce_borrower_owns_loan(loan: dict) -> None:
    """If the caller role is Borrower, verify their X-User-ID matches loan.borrower_id."""
    if g.role == "Borrower" and not borrower_owns_loan(loan, g.user_id):
        raise err_forbidden("Borrower can only act on own loan.")


def parse_version(body: dict):
    v = body.get("version")
    if v is None:
        return None
    if not isinstance(v, int):
        # Try coerce; bad type → treat as concurrent update mismatch.
        try:
            v = int(v)
        except (TypeError, ValueError):
            raise err_concurrent_update()
    return v


def check_version(entity: dict, expected) -> None:
    if expected is None:
        return
    if entity.get("version") != expected:
        raise err_concurrent_update()


def parse_required_date(body: dict, name: str):
    if name not in body or body[name] is None:
        raise ApiError("ERR_INVALID_STATE", 409, f"Missing field {name}")
    try:
        return parse_iso(body[name])
    except Exception:
        raise ApiError("ERR_INVALID_STATE", 409, f"Invalid date for {name}")


def get_int(body: dict, name: str, default: Any = None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool):
        # bools are technically ints in Python; reject them.
        raise ApiError("ERR_INVALID_STATE", 409, f"Invalid integer for {name}")
    if isinstance(val, int):
        return val
    try:
        return int(val)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_STATE", 409, f"Invalid integer for {name}")
