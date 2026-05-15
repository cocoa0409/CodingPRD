"""Optimistic concurrency control helper."""
from __future__ import annotations

from typing import Any

from .errors import ApiError


def check_version(entity: dict[str, Any], body: dict[str, Any]) -> None:
    """If body carries a `version`, ensure it matches entity['version'].

    Per PRD §2.5: when omitted, skip the check.
    """
    if "version" not in body or body["version"] is None:
        return
    try:
        provided = int(body["version"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VERSION_CONFLICT", "Invalid version field.")
    if provided != int(entity.get("version", 0)):
        raise ApiError("ERR_VERSION_CONFLICT", "Stale version.")
