"""TitleSearch service (PRD §3.4)."""

import db
from config import (
    TITLE_CLEAR,
    TITLE_ISSUES,
    TITLE_ORDERED,
    TITLE_RESOLVED,
)
from errors import (
    ERR_INVALID_STATE,
    ERR_RESOURCE_NOT_FOUND,
    ERR_VALIDATION,
    raise_error,
)
from services import clock
from services.common import bump, init_common, occ_check
from services.validation import require_list


def create(application: dict, body: dict) -> dict:
    """Order a TitleSearch (no body fields)."""
    ts = init_common(
        {
            "application_id": application["id"],
            "status": TITLE_ORDERED,
            "defects_found": [],
            "resolved_at": None,
        }
    )
    db.title_searches[ts["id"]] = ts
    return ts


def _get_or_404(application_id: str) -> dict:
    candidates = [t for t in db.title_searches.values() if t["application_id"] == application_id]
    if not candidates:
        raise_error(ERR_RESOURCE_NOT_FOUND, "TitleSearch not found.")
    return max(candidates, key=lambda t: t["created_at"])


def complete(application: dict, body: dict) -> dict:
    ts = _get_or_404(application["id"])
    occ_check(ts, body)
    if ts["status"] != TITLE_ORDERED:
        raise_error(ERR_INVALID_STATE, "TitleSearch must be in ORDERED.")
    defects = require_list(body, "defects_found")
    if any(not isinstance(d, str) for d in defects):
        raise_error(ERR_VALIDATION, "defects_found entries must be strings.")
    ts["defects_found"] = list(defects)
    ts["status"] = TITLE_CLEAR if len(defects) == 0 else TITLE_ISSUES
    bump(ts)
    return ts


def resolve(application: dict, body: dict) -> dict:
    ts = _get_or_404(application["id"])
    occ_check(ts, body)
    if ts["status"] != TITLE_ISSUES:
        raise_error(ERR_INVALID_STATE, "TitleSearch must be in ISSUES_FOUND.")
    ts["status"] = TITLE_RESOLVED
    ts["resolved_at"] = clock.get_now_iso()
    bump(ts)
    return ts
