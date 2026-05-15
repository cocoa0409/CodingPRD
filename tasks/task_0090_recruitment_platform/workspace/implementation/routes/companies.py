"""Company and HrUser binding routes."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

from flask import Blueprint, jsonify

from auth import get_caller, require_roles
from clock import clock, iso_now
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_VALIDATION,
    raise_err,
)
from request_body import check_version, get_json_body, require_field
from response import success_object
from services.cascade import cascade_company_blacklisted
from store import append_audit, bump, init_common_fields, lock, store


bp = Blueprint("companies", __name__)


_INDUSTRY_VALUES = {"TECH", "FINANCE", "MANUFACTURING", "RETAIL", "HEALTHCARE", "EDUCATION", "OTHER"}
_SIZE_BAND_VALUES = {"SMALL", "MEDIUM", "LARGE", "ENTERPRISE"}
_TIER_VALUES = {"BASIC", "PREMIUM"}


def _compute_quota_limit(company: Dict[str, Any]) -> int:
    if company.get("verification_status") != "VERIFIED":
        return 0
    if company.get("verification_tier") == "BASIC":
        return 5
    if company.get("verification_tier") == "PREMIUM":
        return 25
    return 0


def _serialize(company: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(company)
    return out


@bp.post("/recruitment/companies")
def create_company():
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    body = get_json_body()
    legal_name = require_field(body, "legal_name")
    business_license_number = require_field(body, "business_license_number")
    industry = require_field(body, "industry")
    size_band = require_field(body, "size_band")
    verification_tier = body.get("verification_tier", "BASIC")

    if not isinstance(legal_name, str) or not legal_name:
        raise_err(ERR_VALIDATION, "legal_name must be a non-empty string.")
    if not isinstance(business_license_number, str) or not business_license_number:
        raise_err(ERR_VALIDATION, "business_license_number must be a non-empty string.")
    if industry not in _INDUSTRY_VALUES:
        raise_err(ERR_VALIDATION, "industry value invalid.")
    if size_band not in _SIZE_BAND_VALUES:
        raise_err(ERR_VALIDATION, "size_band value invalid.")
    if verification_tier not in _TIER_VALUES:
        raise_err(ERR_VALIDATION, "verification_tier value invalid.")

    with lock():
        # Uniqueness on business_license_number
        for c in store.companies.values():
            if c.get("business_license_number") == business_license_number:
                raise_err(ERR_VALIDATION, "business_license_number is not unique.")

        row = init_common_fields(
            {
                "legal_name": legal_name,
                "business_license_number": business_license_number,
                "industry": industry,
                "size_band": size_band,
                "verification_status": "DRAFT",
                "verification_tier": verification_tier,
                "verified_at": None,
                "reverification_due_at": None,
                "authorized_hr_user_ids": [],
                "active_job_posting_count": 0,
                "posting_quota_limit": 0,
                "blacklist_reason": None,
            }
        )
        store.companies[row["id"]] = row
        body_out, status = success_object(_serialize(row), 201)
        return jsonify(body_out), status


@bp.get("/recruitment/companies/<cid>")
def get_company(cid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser", "PlatformAdmin"])
    company = store.companies.get(cid)
    if company is None:
        raise_err(ERR_NOT_FOUND, "Company not found.")
    body_out, status = success_object(_serialize(company))
    return jsonify(body_out), status


@bp.post("/recruitment/companies/<cid>/submit-verification")
def submit_verification(cid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    company = store.companies.get(cid)
    if company is None:
        raise_err(ERR_NOT_FOUND, "Company not found.")
    body = get_json_body()
    check_version(body, company)
    if company["verification_status"] not in {"DRAFT", "EXPIRED"}:
        raise_err(ERR_INVALID_STATE, "Company cannot submit verification.")
    # Required-fields check
    if not company.get("business_license_number"):
        raise_err(ERR_VALIDATION, "business_license_number missing.")
    if not company.get("industry") or not company.get("size_band"):
        raise_err(ERR_VALIDATION, "industry/size_band missing.")
    if not company.get("verification_tier"):
        raise_err(ERR_VALIDATION, "verification_tier missing.")

    from_state = company["verification_status"]
    company["verification_status"] = "PENDING"
    bump(company)
    append_audit(
        subject_entity="Company",
        subject_id=company["id"],
        event_kind="STATE_TRANSITION",
        from_state=from_state,
        to_state="PENDING",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, status = success_object(_serialize(company))
    return jsonify(body_out), status


@bp.post("/recruitment/companies/<cid>/approve-verification")
def approve_verification(cid: str):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin"])
    company = store.companies.get(cid)
    if company is None:
        raise_err(ERR_NOT_FOUND, "Company not found.")
    body = get_json_body()
    check_version(body, company)
    if company["verification_status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "Company not pending.")

    company["verification_status"] = "VERIFIED"
    now = clock.now()
    from clock import format_iso
    company["verified_at"] = format_iso(now)
    company["reverification_due_at"] = format_iso(now + timedelta(days=365))
    company["posting_quota_limit"] = _compute_quota_limit(company)
    bump(company)
    append_audit(
        subject_entity="Company",
        subject_id=company["id"],
        event_kind="STATE_TRANSITION",
        from_state="PENDING",
        to_state="VERIFIED",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, status = success_object(_serialize(company))
    return jsonify(body_out), status


@bp.post("/recruitment/companies/<cid>/reject-verification")
def reject_verification(cid: str):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin"])
    company = store.companies.get(cid)
    if company is None:
        raise_err(ERR_NOT_FOUND, "Company not found.")
    body = get_json_body()
    check_version(body, company)
    if company["verification_status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "Company not pending.")
    company["verification_status"] = "DRAFT"
    bump(company)
    append_audit(
        subject_entity="Company",
        subject_id=company["id"],
        event_kind="STATE_TRANSITION",
        from_state="PENDING",
        to_state="DRAFT",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, status = success_object(_serialize(company))
    return jsonify(body_out), status


@bp.post("/recruitment/companies/<cid>/blacklist")
def blacklist_company(cid: str):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin"])
    company = store.companies.get(cid)
    if company is None:
        raise_err(ERR_NOT_FOUND, "Company not found.")
    body = get_json_body()
    check_version(body, company)
    blacklist_reason = require_field(body, "blacklist_reason")
    if not isinstance(blacklist_reason, str) or not blacklist_reason.strip():
        raise_err(ERR_VALIDATION, "blacklist_reason must be a non-empty string.")
    if company["verification_status"] not in {"DRAFT", "PENDING", "VERIFIED"}:
        raise_err(ERR_INVALID_STATE, "Company cannot be blacklisted in its current state.")
    from_state = company["verification_status"]
    company["verification_status"] = "BLACKLISTED"
    company["blacklist_reason"] = blacklist_reason
    company["posting_quota_limit"] = 0
    bump(company)
    append_audit(
        subject_entity="Company",
        subject_id=company["id"],
        event_kind="STATE_TRANSITION",
        from_state=from_state,
        to_state="BLACKLISTED",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    if from_state == "VERIFIED":
        cascade_company_blacklisted(company, caller.role, caller.user_id)
    body_out, status = success_object(_serialize(company))
    return jsonify(body_out), status


@bp.post("/recruitment/companies/<cid>/hr-bindings")
def create_hr_binding(cid: str):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin"])
    company = store.companies.get(cid)
    if company is None:
        raise_err(ERR_NOT_FOUND, "Company not found.")
    body = get_json_body()
    email = require_field(body, "email")
    display_name = require_field(body, "display_name")
    if not isinstance(email, str) or not email:
        raise_err(ERR_VALIDATION, "email must be a non-empty string.")
    if not isinstance(display_name, str) or not display_name:
        raise_err(ERR_VALIDATION, "display_name must be a non-empty string.")
    for u in store.hr_users.values():
        if u.get("email") == email:
            raise_err(ERR_VALIDATION, "email is not unique.")
    row = init_common_fields(
        {
            "company_id": cid,
            "email": email,
            "display_name": display_name,
            "binding_status": "ACTIVE",
        }
    )
    store.hr_users[row["id"]] = row
    # Update company's authorized_hr_user_ids
    auth_list = list(company.get("authorized_hr_user_ids") or [])
    if row["id"] not in auth_list:
        auth_list.append(row["id"])
    company["authorized_hr_user_ids"] = auth_list
    bump(company)
    body_out, status = success_object(dict(row), 201)
    return jsonify(body_out), status
