"""Shared helpers consumed by every route module.

Owns:
  - body parsing tolerant to empty/non-JSON requests
  - pagination parameter parsing per PRD §2.3
  - existence lookups that raise the §1.4 priority-4..8 not-found errors
  - ownership enforcement for Customer callers
  - integer/string field coercion that surfaces ERR_VALIDATION

Route handlers never reach into request.args or request.get_json
directly — they call into these helpers so the error semantics stay
uniform.
"""
from __future__ import annotations

from typing import Any, Iterable

from flask import g, request

import config as cfg
from db import store
from errors import (
    ApiError,
    err_account_not_found,
    err_customer_not_found,
    err_options_approval_not_found,
    err_order_not_found,
    err_ownership,
    err_transfer_not_found,
    err_validation,
)


# ── Request body parsing ───────────────────────────────────────────────────


def get_json() -> dict:
    """Return a dict body. Empty body and bad JSON return {} so callers
    can detect missing fields via key absence rather than catching
    parser exceptions."""
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
    if not isinstance(body, dict):
        return {}
    return body


def require_str(body: dict, name: str, *, max_len: int | None = None, min_len: int = 1) -> str:
    val = body.get(name)
    if not isinstance(val, str):
        raise err_validation(f"Missing or non-string field: {name}")
    s = val.strip()
    if len(s) < min_len:
        raise err_validation(f"Field {name} too short")
    if max_len is not None and len(val) > max_len:
        raise err_validation(f"Field {name} too long")
    return val


def get_str(body: dict, name: str, default=None) -> str | None:
    val = body.get(name)
    if val is None:
        return default
    if not isinstance(val, str):
        raise err_validation(f"Field {name} must be a string")
    return val


def require_int(body: dict, name: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    if name not in body or body[name] is None:
        raise err_validation(f"Missing field: {name}")
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err_validation(f"Field {name} must be an integer")
    if minimum is not None and val < minimum:
        raise err_validation(f"Field {name} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise err_validation(f"Field {name} must be <= {maximum}")
    return val


def get_int(body: dict, name: str, default=None) -> int | None:
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err_validation(f"Field {name} must be an integer")
    return val


# ── Pagination (PRD §2.3) ──────────────────────────────────────────────────


def parse_pagination() -> tuple[int, int]:
    """Read limit/offset from query string; reject out-of-bounds with
    ERR_VALIDATION HTTP 422 (PRD §2.3)."""
    raw_limit = request.args.get("limit", str(cfg.DEFAULT_LIMIT))
    raw_offset = request.args.get("offset", str(cfg.DEFAULT_OFFSET))

    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        raise err_validation("limit must be an integer")
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise err_validation("offset must be an integer")

    if limit < cfg.MIN_LIMIT or limit > cfg.MAX_LIMIT:
        raise err_validation(f"limit must be in [{cfg.MIN_LIMIT}, {cfg.MAX_LIMIT}]")
    if offset < 0:
        raise err_validation("offset must be >= 0")

    return limit, offset


def paginate(items: list, limit: int, offset: int) -> list:
    return items[offset : offset + limit]


def sort_by_created_at(items: Iterable[dict]) -> list:
    return sorted(items, key=lambda x: x["created_at"])


# ── Existence resolvers (priority 4-8) ─────────────────────────────────────


def get_customer_or_404(customer_id: str) -> dict:
    c = store.customers.get(customer_id)
    if c is None:
        raise err_customer_not_found()
    return c


def get_account_or_404(account_id: str) -> dict:
    a = store.accounts.get(account_id)
    if a is None:
        raise err_account_not_found()
    return a


def get_options_approval_or_404(oa_id: str) -> dict:
    o = store.options_approvals.get(oa_id)
    if o is None:
        raise err_options_approval_not_found()
    return o


def get_order_or_404(order_id: str) -> dict:
    o = store.orders.get(order_id)
    if o is None:
        raise err_order_not_found()
    return o


def get_transfer_or_404(tid: str) -> dict:
    t = store.acat_transfers.get(tid)
    if t is None:
        raise err_transfer_not_found()
    return t


# ── Ownership (priority 9 / PRD §2.1) ──────────────────────────────────────


def enforce_customer_owns_customer(customer: dict) -> None:
    """Customer role: X-User-ID must equal Customer.id."""
    if g.role != cfg.ROLE_CUSTOMER:
        return
    if customer["id"] != g.user_id:
        raise err_ownership()


def enforce_customer_owns_account(account: dict) -> None:
    if g.role != cfg.ROLE_CUSTOMER:
        return
    if account["customer_id"] != g.user_id:
        raise err_ownership()


def enforce_customer_owns_via_account(account_id: str) -> dict:
    """Resolve an account and run the ownership check. Returns the row."""
    a = get_account_or_404(account_id)
    enforce_customer_owns_account(a)
    return a


# ── Optimistic concurrency (PRD §2.5) ──────────────────────────────────────


def check_version(entity: dict, body: dict) -> None:
    """If body['version'] is supplied and non-null, it must equal the
    entity's current version. PRD §2.5 maps mismatch → ERR_INVALID_STATE
    HTTP 409 (NOT a custom error_id)."""
    if "version" not in body:
        return
    expected = body["version"]
    if expected is None:
        return
    if not isinstance(expected, int) or expected != entity.get("version"):
        from errors import err_invalid_state

        raise err_invalid_state("version mismatch — resource has been modified")
