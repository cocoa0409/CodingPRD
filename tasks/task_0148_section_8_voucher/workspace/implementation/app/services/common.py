"""Shared mutation/pagination helpers used across services."""

from __future__ import annotations

from typing import Iterable, List, Tuple

from app import clock, store
from app.errors import APIError, validation


PAGINATION_DEFAULTS = {"limit": 10, "min": 1, "max": 100, "offset": 0}


def parse_pagination(args) -> Tuple[int, int]:
    """Read `limit` and `offset` from a request.args-like object.

    Enforces 1 <= limit <= 100 and offset >= 0; failures map to ERR_VALIDATION (422).
    """
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = PAGINATION_DEFAULTS["limit"]
    offset = PAGINATION_DEFAULTS["offset"]
    try:
        if raw_limit is not None:
            limit = int(raw_limit)
        if raw_offset is not None:
            offset = int(raw_offset)
    except (TypeError, ValueError) as exc:
        raise validation(f"Invalid pagination parameter: {exc}")
    if limit < PAGINATION_DEFAULTS["min"] or limit > PAGINATION_DEFAULTS["max"]:
        raise validation(
            f"limit must be between {PAGINATION_DEFAULTS['min']} and {PAGINATION_DEFAULTS['max']}"
        )
    if offset < 0:
        raise validation("offset must be non-negative")
    return limit, offset


def paginate(items: List[dict], limit: int, offset: int) -> Tuple[List[dict], int]:
    total = len(items)
    return items[offset:offset + limit], total


def sort_by_created_at(items: Iterable[dict]) -> List[dict]:
    return sorted(items, key=lambda r: (r.get("created_at"), r.get("id", "")))


def touch(entity: dict) -> None:
    """Bump version and updated_at on a mutable entity (common-field aware)."""
    if "version" in entity:
        entity["version"] = entity.get("version", 1) + 1
    if "updated_at" in entity:
        entity["updated_at"] = clock.now()


def fk_lookup(table: dict, key: str):
    """Return entity or raise ERR_FK_NOT_FOUND."""
    if key is None or key not in table:
        from app.errors import fk_not_found
        raise fk_not_found(f"Referenced id {key!r} not found")
    return table[key]


def occ_check(entity: dict, version: int):
    """Optimistic-concurrency check.

    If `version` is None, skip. Otherwise compare to entity['version'] and
    raise ERR_INVALID_STATE/409 on mismatch.
    """
    if version is None:
        return
    if not isinstance(version, int):
        raise validation("version must be an integer when provided")
    if entity.get("version") != version:
        raise APIError("ERR_INVALID_STATE", 409, "version mismatch")
