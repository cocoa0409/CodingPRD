"""Optimistic concurrency control helper."""

from __future__ import annotations

from errors import AppError, ERR_VERSION_CONFLICT


def check_version(row: dict, body: dict | None):
    """If body provides `version`, it must match the stored version."""
    if not body:
        return
    if "version" not in body:
        return
    supplied = body.get("version")
    if supplied is None:
        return
    if supplied != row.get("version"):
        raise AppError(
            ERR_VERSION_CONFLICT,
            "version does not match current",
            409,
        )
