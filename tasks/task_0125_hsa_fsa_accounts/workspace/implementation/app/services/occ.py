"""Optimistic concurrency control helper."""
from __future__ import annotations

from ..errors import ApiError


def check_version(body: dict, current_version: int) -> None:
    """Per PRD §2.4: if `version` is present in body, must match current; else skip."""
    if not isinstance(body, dict):
        return
    if "version" not in body:
        return
    supplied = body.get("version")
    if not isinstance(supplied, int) or isinstance(supplied, bool):
        raise ApiError("ERR_INVALID_STATE", "Optimistic concurrency: version is stale or invalid.")
    if supplied != current_version:
        raise ApiError("ERR_INVALID_STATE", "Optimistic concurrency: version is stale.")
