"""Optimistic concurrency control helpers."""
from __future__ import annotations

from typing import Any

from .errors import ApiError


def check_version(resource: dict, body: dict | None) -> None:
    """If client supplied version, compare to current. Else no check."""
    if body is None or "version" not in body:
        return
    supplied = body["version"]
    if supplied != resource["version"]:
        raise ApiError("ERR_VERSION_CONFLICT")


def bump(resource: dict, now_iso: str) -> None:
    """Increment version and refresh updated_at on a top-level resource."""
    if "version" in resource:
        resource["version"] = resource["version"] + 1
    if "updated_at" in resource:
        resource["updated_at"] = now_iso
