"""Optimistic concurrency control helper (PRD §2.4)."""

from __future__ import annotations

from typing import Any

from errors import err


def check_version(body: dict, row: dict) -> None:
    """If the body supplies `version`, compare to the stored version.

    Per PRD §2.4: when the field is omitted, the check is skipped. A mismatch
    raises ERR_VERSION_CONFLICT.
    """
    if "version" in body and body["version"] is not None:
        supplied = body["version"]
        if not isinstance(supplied, int) or isinstance(supplied, bool):
            raise err("ERR_VALIDATION", "version must be an integer.")
        if supplied != int(row.get("version", 0)):
            raise err("ERR_VERSION_CONFLICT", "Resource has been modified by another writer.")
