"""Optimistic concurrency control helper."""
from __future__ import annotations

from .envelope import err_version_conflict


def check(entity: dict, supplied_version) -> None:
    """If client supplied a version, compare to entity's current; else no-op."""
    if supplied_version is None:
        return
    if not isinstance(supplied_version, int) or isinstance(supplied_version, bool):
        # Non-integer is treated as a validation issue earlier — but we still treat as mismatch here
        raise err_version_conflict("version must be an integer")
    if supplied_version != entity.get("version"):
        raise err_version_conflict("version does not match current resource version")
