"""Core enterprise endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..constants import RISK_RATINGS
from ..errors import api_error
from ..response import success_envelope
from ..store import store
from ..utils import (
    check_version,
    get_json_body,
    optional_bool,
    optional_str,
    require_int,
    require_str,
    validate_ucc,
)

bp = Blueprint("core_enterprises", __name__, url_prefix="/scf/core-enterprises")


READ_ROLES = ("CreditOfficer", "ComplianceOfficer", "RiskReviewer", "CreditApprover", "PlatformAdmin")


# ---- POST /scf/core-enterprises ----
@bp.post("")
@require_auth(["CreditOfficer"])
def create_core_enterprise():
    body = get_json_body()
    legal_name = require_str(body, "legal_name")
    ucc = require_str(body, "unified_credit_code")
    validate_ucc(ucc)
    erp = require_str(body, "erp_endpoint_url")
    joint = body.get("joint_liability_flag", True)
    if joint is None:
        joint = True
    if not isinstance(joint, bool):
        raise api_error("ERR_VALIDATION", "joint_liability_flag must be boolean")
    risk_rating = body.get("risk_rating", "BBB")
    if risk_rating is None:
        risk_rating = "BBB"
    if risk_rating not in RISK_RATINGS:
        raise api_error("ERR_VALIDATION", "risk_rating must be one of AAA, AA, A, BBB, BB")

    # uniqueness on unified_credit_code
    for existing in store.core_enterprises.values():
        if existing.get("unified_credit_code") == ucc:
            raise api_error("ERR_VALIDATION", "unified_credit_code already exists")

    with store.lock:
        payload = {
            "legal_name": legal_name,
            "unified_credit_code": ucc,
            "onboarding_status": "PENDING",
            "credit_line_total_cents": 0,
            "credit_line_reserved_cents": 0,
            "credit_line_consumed_cents": 0,
            "erp_endpoint_url": erp,
            "joint_liability_flag": joint,
            "risk_rating": risk_rating,
        }
        store.stamp_create(payload)
        store.core_enterprises[payload["id"]] = payload
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="CoreEnterprise",
            entity_id=payload["id"],
            action="REGISTER",
        )
    return success_envelope(payload, status=201)


# ---- GET /scf/core-enterprises/{id} ----
@bp.get("/<cid>")
@require_auth(READ_ROLES)
def get_core_enterprise(cid):
    ce = store.core_enterprises.get(cid)
    if ce is None:
        raise api_error("ERR_NOT_FOUND", "Core enterprise not found")
    return success_envelope(ce)


# ---- POST /scf/core-enterprises/{id}/approve ----
@bp.post("/<cid>/approve")
@require_auth(["CreditOfficer"])
def approve_core_enterprise(cid):
    ce = store.core_enterprises.get(cid)
    if ce is None:
        raise api_error("ERR_NOT_FOUND", "Core enterprise not found")
    body = get_json_body()
    if ce.get("onboarding_status") != "PENDING":
        # OCC check still applies if explicitly provided
        check_version(body, ce)
        raise api_error("ERR_INVALID_STATE", "CoreEnterprise is not PENDING")
    check_version(body, ce)
    credit_line_total = require_int(body, "credit_line_total_cents")
    if credit_line_total <= 0:
        raise api_error("ERR_AMOUNT_NON_POSITIVE", "credit_line_total_cents must be > 0")

    with store.lock:
        ce["onboarding_status"] = "APPROVED"
        ce["credit_line_total_cents"] = credit_line_total
        ce["credit_line_reserved_cents"] = 0
        ce["credit_line_consumed_cents"] = 0
        store.stamp_update(ce)
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="CoreEnterprise",
            entity_id=ce["id"],
            action="APPROVE",
            amount_cents=credit_line_total,
        )
        store.emit_event("ERP_SYNC", {"core_enterprise_id": ce["id"], "action": "APPROVE"})
    return success_envelope(ce)


# ---- POST /scf/core-enterprises/{id}/reject ----
@bp.post("/<cid>/reject")
@require_auth(["CreditOfficer"])
def reject_core_enterprise(cid):
    ce = store.core_enterprises.get(cid)
    if ce is None:
        raise api_error("ERR_NOT_FOUND", "Core enterprise not found")
    body = get_json_body()
    if ce.get("onboarding_status") != "PENDING":
        check_version(body, ce)
        raise api_error("ERR_INVALID_STATE", "CoreEnterprise is not PENDING")
    check_version(body, ce)
    with store.lock:
        ce["onboarding_status"] = "REJECTED"
        store.stamp_update(ce)
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="CoreEnterprise",
            entity_id=ce["id"],
            action="REJECT",
        )
    return success_envelope(ce)


# ---- POST /scf/core-enterprises/{id}/suspend ----
@bp.post("/<cid>/suspend")
@require_auth(["ComplianceOfficer"])
def suspend_core_enterprise(cid):
    ce = store.core_enterprises.get(cid)
    if ce is None:
        raise api_error("ERR_NOT_FOUND", "Core enterprise not found")
    body = get_json_body()
    if ce.get("onboarding_status") != "APPROVED":
        check_version(body, ce)
        raise api_error("ERR_INVALID_STATE", "CoreEnterprise is not APPROVED")
    check_version(body, ce)
    reason = require_str(body, "reason")
    with store.lock:
        ce["onboarding_status"] = "SUSPENDED"
        ce["suspend_reason"] = reason
        store.stamp_update(ce)
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="CoreEnterprise",
            entity_id=ce["id"],
            action="REJECT",
        )
    return success_envelope(ce)


# ---- POST /scf/core-enterprises/{id}/reinstate ----
@bp.post("/<cid>/reinstate")
@require_auth(["ComplianceOfficer"])
def reinstate_core_enterprise(cid):
    ce = store.core_enterprises.get(cid)
    if ce is None:
        raise api_error("ERR_NOT_FOUND", "Core enterprise not found")
    body = get_json_body()
    if ce.get("onboarding_status") != "SUSPENDED":
        check_version(body, ce)
        raise api_error("ERR_INVALID_STATE", "CoreEnterprise is not SUSPENDED")
    check_version(body, ce)
    with store.lock:
        ce["onboarding_status"] = "APPROVED"
        store.stamp_update(ce)
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="CoreEnterprise",
            entity_id=ce["id"],
            action="APPROVE",
        )
    return success_envelope(ce)
