"""ExhibitorApplication workflow (§3.3)."""

from __future__ import annotations

import random
from flask import g

import db
import clock
from errors import (
    AppError,
    ERR_NOT_FOUND,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_THEME_MISMATCH,
    ERR_FORBIDDEN,
)
from services.common import stamp_create, bump, check_occ, must_dict
from services import calculations


# -------- create --------
def create_application(exhibition_id: str, body: dict) -> dict:
    ex = db.exhibitions.get(exhibition_id)
    if ex is None:
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    body = must_dict(body)
    theme_tags = body.get("theme_tags")
    if not isinstance(theme_tags, list):
        raise AppError(ERR_INVALID_INPUT, "theme_tags must be an array.", 422)
    requested_tier = body.get("requested_tier")
    if requested_tier not in ("STANDARD", "PREMIUM", "ISLAND"):
        raise AppError(ERR_INVALID_INPUT, "Invalid requested_tier.", 422)
    sponsorship_level = body.get("sponsorship_level", "NONE") or "NONE"
    if sponsorship_level not in ("NONE", "BRONZE", "SILVER", "GOLD", "PLATINUM"):
        raise AppError(ERR_INVALID_INPUT, "Invalid sponsorship_level.", 422)
    seniority_years = body.get("seniority_years", 0)
    if seniority_years is None:
        seniority_years = 0
    if not isinstance(seniority_years, int) or seniority_years < 0:
        raise AppError(ERR_INVALID_INPUT, "seniority_years must be a non-negative integer.", 422)
    row = {
        "exhibition_id": exhibition_id,
        "exhibitor_id": g.user_id,
        "theme_tags": list(theme_tags),
        "requested_tier": requested_tier,
        "sponsorship_level": sponsorship_level,
        "seniority_years": int(seniority_years),
        "lottery_token": None,
        "priority_score": 0.0,
        "status": "DRAFT",
        "rejection_reason": None,
    }
    stamp_create(row)
    db.applications[row["id"]] = row
    return row


def _get_app(application_id: str) -> dict:
    a = db.applications.get(application_id)
    if a is None:
        raise AppError(ERR_NOT_FOUND, "Application not found.", 404)
    return a


def _check_owner(app):
    if g.role == "Exhibitor" and app["exhibitor_id"] != g.user_id:
        raise AppError(ERR_FORBIDDEN, "Application not owned by exhibitor.", 403)


def submit_application(application_id: str, body: dict) -> dict:
    a = _get_app(application_id)
    _check_owner(a)
    ex = db.exhibitions.get(a["exhibition_id"])
    if ex is None:
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    if a["status"] != "DRAFT":
        raise AppError(ERR_INVALID_STATE, "Application not in DRAFT.", 409)
    if ex["status"] != "INTAKE_OPEN":
        raise AppError(ERR_INVALID_STATE, "Exhibition not in INTAKE_OPEN.", 409)
    check_occ(a, body)
    a["lottery_token"] = random.randint(0, 999999)
    a["priority_score"] = calculations.application_priority_score(
        a["sponsorship_level"], a["seniority_years"], a["lottery_token"]
    )
    a["status"] = "SUBMITTED"
    bump(a)
    return a


def start_review(application_id: str, body: dict) -> dict:
    a = _get_app(application_id)
    if a["status"] != "SUBMITTED":
        raise AppError(ERR_INVALID_STATE, "Application not in SUBMITTED.", 409)
    check_occ(a, body)
    a["status"] = "UNDER_REVIEW"
    bump(a)
    return a


def qualify_application(application_id: str, body: dict) -> dict:
    a = _get_app(application_id)
    ex = db.exhibitions.get(a["exhibition_id"])
    if ex is None:
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    if a["status"] != "UNDER_REVIEW":
        raise AppError(ERR_INVALID_STATE, "Application not in UNDER_REVIEW.", 409)
    theme = (ex.get("theme_code") or "").strip()
    tags = set(a.get("theme_tags") or [])
    if theme not in tags:
        raise AppError(
            ERR_THEME_MISMATCH,
            "Application theme_tags does not include the exhibition theme_code.",
            422,
        )
    check_occ(a, body)
    a["status"] = "QUALIFIED"
    bump(a)
    return a


def reject_application(application_id: str, body: dict) -> dict:
    a = _get_app(application_id)
    if a["status"] != "UNDER_REVIEW":
        raise AppError(ERR_INVALID_STATE, "Application not in UNDER_REVIEW.", 409)
    body = must_dict(body)
    reason = body.get("rejection_reason")
    if not reason or not isinstance(reason, str) or not reason.strip():
        raise AppError(ERR_INVALID_INPUT, "rejection_reason is required.", 422)
    check_occ(a, body)
    a["rejection_reason"] = reason
    a["status"] = "REJECTED"
    bump(a)
    return a


def withdraw_application(application_id: str, body: dict) -> dict:
    a = _get_app(application_id)
    _check_owner(a)
    if a["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise AppError(ERR_INVALID_STATE, "Application not in SUBMITTED or UNDER_REVIEW.", 409)
    check_occ(a, body)
    a["status"] = "WITHDRAWN"
    bump(a)
    return a


def list_applications(exhibition_id: str, status_filter: str | None, sort_by: str | None,
                      limit: int, offset: int):
    ex = db.exhibitions.get(exhibition_id)
    if ex is None:
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    items = [a for a in db.applications.values() if a["exhibition_id"] == exhibition_id]
    if status_filter:
        items = [a for a in items if a["status"] == status_filter]
    if sort_by == "priority_score":
        items.sort(key=lambda a: (-float(a.get("priority_score") or 0.0), a["created_at"]))
    else:
        items.sort(key=lambda a: a["created_at"])
    return items[offset:offset + limit], len(items)
