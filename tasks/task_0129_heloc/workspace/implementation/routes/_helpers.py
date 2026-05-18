"""Route-layer helpers: body parsing, pagination, ownership checks."""
from __future__ import annotations

import json
from typing import Any, Iterable

from flask import g, request

from config import DEFAULT_LIMIT, DEFAULT_OFFSET, MAX_LIMIT, MIN_LIMIT
from db import store
from errors import (
    err_forbidden,
    err_not_found,
    err_validation_failed,
    err_version_conflict,
)


# ── Body parsing ───────────────────────────────────────────────────────────


def get_json() -> dict:
    """Return the request body as a dict (always); tolerates empty bodies."""
    if request.is_json:
        body = request.get_json(silent=True)
    else:
        raw = request.get_data(as_text=True) or ""
        if not raw.strip():
            return {}
        try:
            body = json.loads(raw)
        except Exception:
            raise err_validation_failed("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err_validation_failed("Request body must be a JSON object.")
    return body


def require_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise err_validation_failed(f"Missing required field: {name}.")
    return body[name]


def get_int(body: dict, name: str, *, required: bool = False, default: Any = None):
    """Pull an integer-typed field from the body with strict shape checks."""
    if name not in body or body[name] is None:
        if required:
            raise err_validation_failed(f"Missing required field: {name}.")
        return default
    val = body[name]
    if isinstance(val, bool):
        raise err_validation_failed(f"Field {name} must be an integer (got boolean).")
    if isinstance(val, int):
        return val
    raise err_validation_failed(f"Field {name} must be an integer.")


def get_string(body: dict, name: str, *, required: bool = False, default: Any = None):
    if name not in body or body[name] is None:
        if required:
            raise err_validation_failed(f"Missing required field: {name}.")
        return default
    val = body[name]
    if not isinstance(val, str):
        raise err_validation_failed(f"Field {name} must be a string.")
    return val


def get_bool(body: dict, name: str, *, default: bool = False):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise err_validation_failed(f"Field {name} must be a boolean.")
    return val


def get_enum(body: dict, name: str, allowed: set, *, required: bool = False, default: Any = None):
    if name not in body or body[name] is None:
        if required:
            raise err_validation_failed(f"Missing required field: {name}.")
        return default
    val = body[name]
    if val not in allowed:
        raise err_validation_failed(
            f"Field {name}={val!r} is not one of {sorted(allowed)}."
        )
    return val


# ── Pagination (scaffold §1.0 pagination_defaults) ─────────────────────────


def parse_pagination():
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


# ── Existence lookups (priority 6 — path resolution) ───────────────────────


def get_borrower_or_404(borrower_id: str) -> dict:
    b = store.borrowers.get(borrower_id)
    if b is None:
        raise err_not_found(f"Borrower {borrower_id!s} not found.")
    return b


def get_property_or_404(property_id: str) -> dict:
    p = store.properties.get(property_id)
    if p is None:
        raise err_not_found(f"Property {property_id!s} not found.")
    return p


def get_senior_lien_or_404(senior_lien_id: str) -> dict:
    s = store.senior_liens.get(senior_lien_id)
    if s is None:
        raise err_not_found(f"SeniorLien {senior_lien_id!s} not found.")
    return s


def get_heloc_or_404(heloc_id: str) -> dict:
    h = store.helocs.get(heloc_id)
    if h is None:
        raise err_not_found(f"Heloc {heloc_id!s} not found.")
    return h


# ── Borrower-scope read identity check (priority 4) ────────────────────────


def enforce_borrower_owns_heloc(heloc: dict) -> None:
    if g.role == "Borrower" and heloc["borrower_id"] != g.user_id:
        raise err_forbidden("Borrower can only read their own HELOC resources.")


def enforce_borrower_owns_property(prop: dict) -> None:
    if g.role == "Borrower" and prop["borrower_id"] != g.user_id:
        raise err_forbidden("Borrower can only read their own Property.")


def enforce_borrower_owns_senior_lien(lien: dict) -> None:
    if g.role != "Borrower":
        return
    prop = store.properties.get(lien["property_id"])
    if prop is None or prop["borrower_id"] != g.user_id:
        raise err_forbidden("Borrower can only read their own SeniorLien.")


def enforce_borrower_self(borrower_id: str) -> None:
    if g.role == "Borrower" and borrower_id != g.user_id:
        raise err_forbidden("Borrower can only read their own borrower record.")


# ── OCC (priority 33) ──────────────────────────────────────────────────────


def parse_version(body: dict):
    """Return the supplied version (int) or None if absent.

    A non-int value yields ERR_VALIDATION_FAILED at parse time; a
    valid int that does not match heloc.version yields
    ERR_VERSION_CONFLICT at the check site.
    """
    if "version" not in body or body["version"] is None:
        return None
    v = body["version"]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation_failed("Field version must be an integer.")
    return v


def check_version(entity: dict, expected) -> None:
    if expected is None:
        return
    if entity.get("version") != expected:
        raise err_version_conflict()
