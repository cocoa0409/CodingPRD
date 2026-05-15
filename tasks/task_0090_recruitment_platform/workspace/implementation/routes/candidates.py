"""Candidate routes."""
from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify

from auth import get_caller, require_roles
from clock import clock, parse_iso
from errors import (
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_RESUME_NOT_VISIBLE,
    ERR_VALIDATION,
    raise_err,
)
from request_body import check_version, get_json_body, require_field
from response import success_object
from store import bump, init_common_fields, lock, store


bp = Blueprint("candidates", __name__)

_VIS_VALUES = {"PUBLIC", "COMPANY_ONLY", "HIDDEN"}


def _serialize(c: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(c)
    out["applications_last_60s_count"] = _count_recent_applications(c["id"])
    return out


def _count_recent_applications(candidate_id: str) -> int:
    now = clock.now()
    count = 0
    for a in store.applications.values():
        if a.get("candidate_id") != candidate_id:
            continue
        try:
            ts = parse_iso(a.get("created_at", ""))
        except Exception:
            continue
        delta = (now - ts).total_seconds()
        if 0 <= delta < 60:
            count += 1
    return count


def check_resume_visible_to_hr(candidate: Dict[str, Any], company_id: str) -> None:
    """Visibility gate for HR-side accessors. Returns None if OK, raises otherwise."""
    mode = candidate.get("visibility_mode")
    if mode == "PUBLIC":
        return
    if mode == "HIDDEN":
        raise_err(ERR_RESUME_NOT_VISIBLE, "Candidate resume is HIDDEN.")
    if mode == "COMPANY_ONLY":
        if company_id in (candidate.get("visible_to_company_ids") or []):
            return
        raise_err(ERR_RESUME_NOT_VISIBLE, "Company not whitelisted.")
    raise_err(ERR_RESUME_NOT_VISIBLE, "Unknown visibility_mode.")


@bp.post("/recruitment/candidates")
def create_candidate():
    caller = get_caller()
    require_roles(caller, ["Candidate"])
    body = get_json_body()
    full_name = require_field(body, "full_name")
    email = require_field(body, "email")
    resume_attachment_url = require_field(body, "resume_attachment_url")
    visibility_mode = body.get("visibility_mode", "PUBLIC")
    visible_to_company_ids = body.get("visible_to_company_ids", [])

    if not isinstance(full_name, str) or not full_name:
        raise_err(ERR_VALIDATION, "full_name must be a non-empty string.")
    if not isinstance(email, str) or not email:
        raise_err(ERR_VALIDATION, "email must be a non-empty string.")
    if not isinstance(resume_attachment_url, str) or not resume_attachment_url:
        raise_err(ERR_VALIDATION, "resume_attachment_url must be a non-empty string.")
    if visibility_mode not in _VIS_VALUES:
        raise_err(ERR_VALIDATION, "visibility_mode invalid.")
    if not isinstance(visible_to_company_ids, list):
        raise_err(ERR_VALIDATION, "visible_to_company_ids must be an array.")

    for c in store.candidates.values():
        if c.get("email") == email:
            raise_err(ERR_VALIDATION, "email is not unique.")

    row = init_common_fields(
        {
            "full_name": full_name,
            "email": email,
            "resume_attachment_url": resume_attachment_url,
            "visibility_mode": visibility_mode,
            "visible_to_company_ids": list(visible_to_company_ids),
            "last_application_at": None,
        }
    )
    store.candidates[row["id"]] = row
    body_out, status = success_object(_serialize(row), 201)
    return jsonify(body_out), status


@bp.patch("/recruitment/candidates/<cid>")
def update_candidate(cid: str):
    caller = get_caller()
    require_roles(caller, ["Candidate"])
    candidate = store.candidates.get(cid)
    if candidate is None:
        raise_err(ERR_NOT_FOUND, "Candidate not found.")
    if caller.user_id != cid:
        # Candidate can only edit their own row.
        raise_err(ERR_FORBIDDEN, "Cannot edit another candidate.")
    body = get_json_body()
    check_version(body, candidate)

    if "visibility_mode" in body:
        vm = body["visibility_mode"]
        if vm not in _VIS_VALUES:
            raise_err(ERR_VALIDATION, "visibility_mode invalid.")
        candidate["visibility_mode"] = vm
    if "visible_to_company_ids" in body:
        vc = body["visible_to_company_ids"]
        if not isinstance(vc, list):
            raise_err(ERR_VALIDATION, "visible_to_company_ids must be an array.")
        candidate["visible_to_company_ids"] = list(vc)
    if "resume_attachment_url" in body:
        url = body["resume_attachment_url"]
        if not isinstance(url, str) or not url:
            raise_err(ERR_VALIDATION, "resume_attachment_url must be a non-empty string.")
        candidate["resume_attachment_url"] = url

    bump(candidate)
    body_out, status = success_object(_serialize(candidate))
    return jsonify(body_out), status


@bp.get("/recruitment/candidates/<cid>")
def get_candidate(cid: str):
    caller = get_caller()
    require_roles(caller, ["Candidate", "HrUser"])
    candidate = store.candidates.get(cid)
    if candidate is None:
        raise_err(ERR_NOT_FOUND, "Candidate not found.")
    if caller.role == "Candidate":
        if caller.user_id != cid:
            raise_err(ERR_FORBIDDEN, "Cannot view another candidate.")
    else:
        # HrUser caller — apply visibility rule using acting company.
        hr_user = store.hr_users.get(caller.user_id)
        if hr_user is None:
            raise_err(ERR_FORBIDDEN, "Acting HrUser not found.")
        check_resume_visible_to_hr(candidate, hr_user.get("company_id"))
    body_out, status = success_object(_serialize(candidate))
    return jsonify(body_out), status
