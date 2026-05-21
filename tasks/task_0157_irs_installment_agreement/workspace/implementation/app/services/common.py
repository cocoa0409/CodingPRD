"""Common helpers used across services: OCC, common-field bumps, snapshot."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional

from app.errors import ERR_VERSION_CONFLICT, raise_error
from app.timeutil import now_iso


def check_version(resource: dict, supplied: Optional[int]):
    """Optimistic concurrency check (validation priority 23).

    When `supplied` is None, the check is skipped.
    When `supplied` is provided, must equal `resource['version']`.
    """
    if supplied is None:
        return
    if resource.get("version") != supplied:
        raise_error(
            ERR_VERSION_CONFLICT,
            f"Version mismatch: supplied {supplied}, stored {resource.get('version')}.",
        )


def bump_version(resource: dict) -> None:
    """Refresh updated_at and increment version on a mutation."""
    if "version" in resource:
        resource["version"] = (resource.get("version") or 0) + 1
    if "updated_at" in resource or "created_at" in resource:
        resource["updated_at"] = now_iso()


def init_common_fields(resource: dict, *, with_version: bool = True) -> None:
    """Stamp created_at/updated_at/version on a new resource."""
    ts = now_iso()
    resource["created_at"] = ts
    if with_version:
        resource["updated_at"] = ts
        resource["version"] = 1


def deep_copy(d: Any) -> Any:
    return deepcopy(d)
