"""Entity lookups and datetime parsing helpers.

Path-id lookups raise ERR_NOT_FOUND; body-FK lookups raise
ERR_REFERENCED_ENTITY_NOT_FOUND (or ERR_APPLICANT_NOT_FOUND for the application
creation specialization). See PRD §2.5.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import db
from errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
)


def get_or_404(store: dict, ident: str, what: str = "resource") -> dict:
    rec = store.get(ident)
    if rec is None:
        raise APIError(ERR_NOT_FOUND, 404, f"{what} not found")
    return rec


def get_or_referenced(store: dict, ident: str, what: str = "referenced resource") -> dict:
    rec = store.get(ident)
    if rec is None:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 404, f"{what} does not exist")
    return rec


def parse_iso_utc(value: str) -> Optional[datetime]:
    """Parse a strict ISO 8601 UTC datetime. Returns None if unparseable.

    Accepts trailing 'Z' or an explicit +00:00 offset and bare (naive) values,
    which are treated as UTC.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    candidate = raw
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def program_by_code(code: str) -> Optional[dict]:
    for p in db.programs.values():
        if p.get("code") == code:
            return p
    return None
