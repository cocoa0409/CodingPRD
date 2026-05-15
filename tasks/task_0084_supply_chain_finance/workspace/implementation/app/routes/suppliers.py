"""Supplier endpoints (PRD §3.2)."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import clock
from ..constants import (
    AML_BLACKLIST_THRESHOLD,
    KYC_STATUSES,
    MAX_EXTENSION_TIER,
)
from ..errors import api_error
from ..response import success_envelope
from ..services.cascades import cascade_blacklist_supplier
from ..store import fmt_ts, store
from ..utils import (
    check_version,
    get_json_body,
    optional_str,
    require_int,
    require_number,
    require_str,
    validate_ucc,
)

bp = Blueprint("suppliers", __name__, url_prefix="/scf/suppliers")


READ_ROLES = ("SupplierUser", "ComplianceOfficer", "RiskReviewer", "CreditApprover", "PlatformAdmin")


# ---- POST /scf/suppliers ----
@bp.post("")
@require_auth(["PlatformAdmin"])
def create_supplier():
    body = get_json_body()
    legal_name = require_str(body, "legal_name")
    ucc = require_str(body, "unified_credit_code")
    validate_ucc(ucc)
    tier = require_int(body, "tier_to_core")
    if tier < 1 or tier > MAX_EXTENSION_TIER:
        raise api_error("ERR_TIER_TOO_DEEP", "tier_to_core exceeds MAX_EXTENSION_TIER")
    parent_supplier_id = optional_str(body, "parent_supplier_id", None)
    if tier >= 2:
        if not parent_supplier_id:
            raise api_error("ERR_VALIDATION", "parent_supplier_id is required for tier >= 2")
        if parent_supplier_id not in store.suppliers:
            raise api_error("ERR_REFERENCED_NOT_FOUND", "parent_supplier_id not found")
    else:
        parent_supplier_id = None
    bank_account = require_str(body, "bank_account_number")

    # uniqueness on unified_credit_code
    for existing in store.suppliers.values():
        if existing.get("unified_credit_code") == ucc:
            raise api_error("ERR_VALIDATION", "unified_credit_code already exists")

    with store.lock:
        payload = {
            "legal_name": legal_name,
            "unified_credit_code": ucc,
            "tier_to_core": tier,
            "parent_supplier_id": parent_supplier_id,
            "kyc_status": "NOT_RUN",
            "kyc_completed_at": None,
            "aml_risk_score": 0.00,
            "bank_account_number": bank_account,
            "status": "ACTIVE",
        }
        store.stamp_create(payload)
        store.suppliers[payload["id"]] = payload
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="Supplier",
            entity_id=payload["id"],
            action="REGISTER",
        )
    return success_envelope(payload, status=201)


# ---- POST /scf/suppliers/{id}/kyc ----
@bp.post("/<sid>/kyc")
@require_auth(["ComplianceOfficer"])
def kyc_supplier(sid):
    supplier = store.suppliers.get(sid)
    if supplier is None:
        raise api_error("ERR_NOT_FOUND", "Supplier not found")
    body = get_json_body()
    check_version(body, supplier)
    kyc_status = require_str(body, "kyc_status")
    if kyc_status not in KYC_STATUSES:
        raise api_error("ERR_VALIDATION", "kyc_status invalid")
    aml = require_number(body, "aml_risk_score")
    if aml < 0.0 or aml > 1.0:
        raise api_error("ERR_VALIDATION", "aml_risk_score must be in [0.00, 1.00]")
    # round to 2 decimals
    aml = round(aml + 1e-9, 2)

    with store.lock:
        supplier["kyc_status"] = kyc_status
        supplier["aml_risk_score"] = aml
        if kyc_status == "PASSED":
            supplier["kyc_completed_at"] = fmt_ts(clock.now())
        store.stamp_update(supplier)
        # Cascade blacklist if applicable
        if kyc_status == "FAILED" or aml >= AML_BLACKLIST_THRESHOLD:
            cascade_blacklist_supplier(supplier)
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="Supplier",
            entity_id=supplier["id"],
            action="REGISTER",
        )
    return success_envelope(supplier)


# ---- GET /scf/suppliers/{id} ----
@bp.get("/<sid>")
@require_auth(READ_ROLES)
def get_supplier(sid):
    supplier = store.suppliers.get(sid)
    if supplier is None:
        raise api_error("ERR_NOT_FOUND", "Supplier not found")
    # Ownership for SupplierUser
    if g.user_role == "SupplierUser" and g.user_id != supplier["id"]:
        raise api_error("ERR_OWNERSHIP_VIOLATION", "SupplierUser does not own this supplier")
    return success_envelope(supplier)
