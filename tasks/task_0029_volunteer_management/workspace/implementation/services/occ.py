"""Optimistic concurrency control helper."""
from __future__ import annotations

from errors import ERR_VERSION_CONFLICT, err


def check_occ(row: dict, body: dict | None) -> None:
    """If body carries a 'version' key (non-None), it must equal row['version']."""
    if not isinstance(body, dict):
        return
    if "version" not in body or body["version"] is None:
        return
    if body["version"] != row.get("version"):
        raise err(ERR_VERSION_CONFLICT, "version mismatch")
