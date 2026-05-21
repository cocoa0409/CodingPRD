"""Helpers for the common-resource audit-trail and OCC checks."""

from __future__ import annotations

from typing import Any

from clock import CLOCK
from errors import APIError
from ids import new_id


def make_versioned(extra: dict[str, Any]) -> dict[str, Any]:
    now = CLOCK.now_iso()
    base = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    base.update(extra)
    return base


def make_simple(extra: dict[str, Any]) -> dict[str, Any]:
    """For Assignment / RouteGroup / Fine — id + created_at only."""
    base = {"id": new_id(), "created_at": CLOCK.now_iso()}
    base.update(extra)
    return base


def touch(resource: dict[str, Any]) -> None:
    """Refresh updated_at and bump version on a versioned resource."""
    resource["updated_at"] = CLOCK.now_iso()
    if "version" in resource:
        resource["version"] = int(resource["version"]) + 1


def check_version(resource: dict[str, Any], supplied: Any) -> None:
    """If supplied is not None, raise on mismatch."""
    if supplied is None:
        return
    try:
        sv = int(supplied)
    except (TypeError, ValueError):
        raise APIError("ERR_VALIDATION", "version must be an integer")
    if sv != int(resource.get("version", 0)):
        raise APIError("ERR_VERSION_CONFLICT")
