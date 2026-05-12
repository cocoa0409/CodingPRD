"""Optimistic concurrency control helper (PRD §2.10)."""

from __future__ import annotations

from errors import AppError, ERR_VALIDATION_FAILED, ERR_VERSION_CONFLICT


def check(record: dict, body: dict | None) -> None:
    """If body has a `version` field, compare against record['version']."""
    if not body or "version" not in body or body["version"] is None:
        return
    supplied = body["version"]
    if isinstance(supplied, bool) or not isinstance(supplied, int):
        raise AppError(ERR_VALIDATION_FAILED, "version must be an integer", 422)
    current = record.get("version")
    if supplied != current:
        raise AppError(ERR_VERSION_CONFLICT,
                       f"version mismatch: supplied {supplied}, current {current}",
                       409)
