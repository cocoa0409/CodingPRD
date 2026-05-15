"""Payable confirmation endpoints (PRD §3.3)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g, request

from ..auth import require_auth
from ..clock import clock
from ..constants import MAX_DUE_DATE_DAYS, MAX_EXTENSION_TIER
from ..errors import api_error
from ..response import list_envelope, success_envelope
from ..services.cascades import cascade_revoke_confirmation, latest_confirmation_for_supplier
from ..store import fmt_ts, store
from ..utils import (
    check_version,
    get_json_body,
    page_slice,
    parse_iso_datetime,
    parse_pagination,
    require_int,
    require_str,
)

bp = Blueprint("payable_confirmations", __name__, url_prefix="/scf/payable-confirmations")


READ_ROLES = (
    "CoreEnterpriseUser",
    "SupplierUser",
    "RiskReviewer",
    "CreditApprover",
    "PlatformAdmin",
)


# ---- POST /scf/payable-confirmations ----
@bp.post("")
@require_auth(["CoreEnterpriseUser"])
def create_payable_confirmation():
    body = get_json_body()
    core_id = require_str(body, "core_enterprise_id")
    supplier_id = require_str(body, "supplier_id")
    invoice_number = require_str(body, "invoice_number")
    contract_number = require_str(body, "contract_number")
    amount_cents = require_int(body, "amount_cents")
    due_date_raw = require_str(body, "due_date")
    due_date = parse_iso_datetime(due_date_raw)

    # Ownership: CoreEnterpriseUser owns this core_enterprise_id
    if g.user_id != core_id:
        raise api_error("ERR_OWNERSHIP_VIOLATION", "CoreEnterpriseUser does not own this core_enterprise_id")

    ce = store.core_enterprises.get(core_id)
    if ce is None:
        raise api_error("ERR_REFERENCED_NOT_FOUND", "core_enterprise_id not found")
    supplier = store.suppliers.get(supplier_id)
    if supplier is None:
        raise api_error("ERR_REFERENCED_NOT_FOUND", "supplier_id not found")

    if ce.get("onboarding_status") != "APPROVED":
        raise api_error("ERR_CORE_ENTERPRISE_NOT_APPROVED", "CoreEnterprise is not APPROVED")
    if supplier.get("status") == "BLACKLISTED":
        raise api_error("ERR_SUPPLIER_BLACKLISTED", "Supplier is BLACKLISTED")
    if supplier.get("status") != "ACTIVE":
        raise api_error("ERR_INVALID_STATE", "Supplier is not ACTIVE")

    tier = int(supplier["tier_to_core"])
    if tier > MAX_EXTENSION_TIER:
        raise api_error("ERR_TIER_TOO_DEEP", "Supplier tier exceeds MAX_EXTENSION_TIER")

    if amount_cents <= 0:
        raise api_error("ERR_AMOUNT_NON_POSITIVE", "amount_cents must be > 0")

    now = clock.now()
    if due_date <= now or due_date > now + timedelta(days=MAX_DUE_DATE_DAYS):
        raise api_error("ERR_DUE_DATE_OUT_OF_RANGE", "due_date out of permitted window")

    # Tier-parent check at upload: parent must have a CONFIRMED/SETTLED confirmation
    if tier >= 2:
        parent_id = supplier.get("parent_supplier_id")
        if not parent_id:
            raise api_error("ERR_TIER_PARENT_NOT_CONFIRMED", "Parent supplier missing for tier >= 2")
        parent_conf = latest_confirmation_for_supplier(parent_id)
        if parent_conf is None:
            raise api_error("ERR_TIER_PARENT_NOT_CONFIRMED", "Upstream parent confirmation is not CONFIRMED/SETTLED")

    with store.lock:
        payload = {
            "core_enterprise_id": core_id,
            "supplier_id": supplier_id,
            "invoice_number": invoice_number,
            "contract_number": contract_number,
            "amount_cents": amount_cents,
            "due_date": fmt_ts(due_date),
            "tier": tier,
            "status": "PENDING_CONFIRM",
            "confirmed_at": None,
            "revoke_reason": None,
        }
        store.stamp_create(payload)
        store.payable_confirmations[payload["id"]] = payload
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="PayableConfirmation",
            entity_id=payload["id"],
            action="REGISTER",
            amount_cents=amount_cents,
        )
    return success_envelope(payload, status=201)


# ---- POST /scf/payable-confirmations/{id}/confirm ----
@bp.post("/<cid>/confirm")
@require_auth(["CoreEnterpriseUser"])
def confirm_payable_confirmation(cid):
    conf = store.payable_confirmations.get(cid)
    if conf is None:
        raise api_error("ERR_NOT_FOUND", "Payable confirmation not found")
    if g.user_id != conf.get("core_enterprise_id"):
        raise api_error("ERR_OWNERSHIP_VIOLATION", "CoreEnterpriseUser does not own this confirmation")
    body = get_json_body()
    if conf.get("status") != "PENDING_CONFIRM":
        check_version(body, conf)
        raise api_error("ERR_INVALID_STATE", "Confirmation is not in PENDING_CONFIRM")
    check_version(body, conf)

    ce = store.core_enterprises.get(conf["core_enterprise_id"])
    if ce is None:
        raise api_error("ERR_REFERENCED_NOT_FOUND", "Core enterprise not found")
    if ce.get("onboarding_status") != "APPROVED":
        raise api_error("ERR_CORE_ENTERPRISE_NOT_APPROVED", "CoreEnterprise not APPROVED")

    amount = int(conf["amount_cents"])
    available = (
        int(ce.get("credit_line_total_cents", 0))
        - int(ce.get("credit_line_reserved_cents", 0))
        - int(ce.get("credit_line_consumed_cents", 0))
    )
    if amount > available:
        raise api_error("ERR_CREDIT_LINE_INSUFFICIENT", "Available headroom below amount")

    # Tier-parent re-check at confirm
    tier = int(conf.get("tier", 1))
    if tier >= 2:
        supplier = store.suppliers.get(conf["supplier_id"])
        parent_id = supplier.get("parent_supplier_id") if supplier else None
        if not parent_id:
            raise api_error("ERR_TIER_PARENT_NOT_CONFIRMED", "Parent supplier missing")
        parent_conf = latest_confirmation_for_supplier(parent_id)
        if parent_conf is None:
            raise api_error("ERR_TIER_PARENT_NOT_CONFIRMED", "Parent confirmation not CONFIRMED/SETTLED")

    with store.lock:
        ce["credit_line_reserved_cents"] = int(ce.get("credit_line_reserved_cents", 0)) + amount
        store.stamp_update(ce)
        conf["status"] = "CONFIRMED"
        conf["confirmed_at"] = fmt_ts(clock.now())
        store.stamp_update(conf)
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="PayableConfirmation",
            entity_id=conf["id"],
            action="CONFIRM",
            amount_cents=amount,
        )
        store.emit_event("ERP_SYNC", {"confirmation_id": conf["id"], "action": "CONFIRM"})
    return success_envelope(conf)


# ---- POST /scf/payable-confirmations/{id}/revoke ----
@bp.post("/<cid>/revoke")
@require_auth(["CoreEnterpriseUser"])
def revoke_payable_confirmation(cid):
    conf = store.payable_confirmations.get(cid)
    if conf is None:
        raise api_error("ERR_NOT_FOUND", "Payable confirmation not found")
    if g.user_id != conf.get("core_enterprise_id"):
        raise api_error("ERR_OWNERSHIP_VIOLATION", "CoreEnterpriseUser does not own this confirmation")
    body = get_json_body()
    if conf.get("status") != "CONFIRMED":
        check_version(body, conf)
        raise api_error("ERR_INVALID_STATE", "Confirmation is not in CONFIRMED")
    check_version(body, conf)
    revoke_reason = require_str(body, "revoke_reason")

    # Cannot revoke if a linked Receivable is FINANCED
    for receivable in store.receivables.values():
        if receivable.get("confirmation_id") == conf["id"] and receivable.get("status") == "FINANCED":
            raise api_error("ERR_CONFIRMATION_FROZEN_BY_FINANCING", "Receivable is FINANCED")

    with store.lock:
        conf["status"] = "REVOKED"
        conf["revoke_reason"] = revoke_reason
        store.stamp_update(conf)
        cascade_revoke_confirmation(conf, g.user_role, g.user_id)
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="PayableConfirmation",
            entity_id=conf["id"],
            action="REVOKE",
            amount_cents=int(conf["amount_cents"]),
        )
    return success_envelope(conf)


# ---- GET /scf/payable-confirmations ----
@bp.get("")
@require_auth(READ_ROLES)
def list_payable_confirmations():
    limit, offset = parse_pagination()
    core_id = request.args.get("core_enterprise_id")
    supplier_id = request.args.get("supplier_id")
    status = request.args.get("status")
    tier = request.args.get("tier")

    items = list(store.payable_confirmations.values())
    if core_id:
        items = [c for c in items if c.get("core_enterprise_id") == core_id]
    if supplier_id:
        items = [c for c in items if c.get("supplier_id") == supplier_id]
    if status:
        items = [c for c in items if c.get("status") == status]
    if tier:
        try:
            tier_i = int(tier)
            items = [c for c in items if c.get("tier") == tier_i]
        except ValueError:
            raise api_error("ERR_VALIDATION", "tier must be integer")
    # Owner scoping
    if g.user_role == "CoreEnterpriseUser":
        items = [c for c in items if c.get("core_enterprise_id") == g.user_id]
    elif g.user_role == "SupplierUser":
        items = [c for c in items if c.get("supplier_id") == g.user_id]
    items.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    page, total = page_slice(items, limit, offset)
    return list_envelope(page, total, limit, offset)


# ---- GET /scf/payable-confirmations/{id} ----
@bp.get("/<cid>")
@require_auth(READ_ROLES)
def get_payable_confirmation(cid):
    conf = store.payable_confirmations.get(cid)
    if conf is None:
        raise api_error("ERR_NOT_FOUND", "Payable confirmation not found")
    if g.user_role == "CoreEnterpriseUser" and g.user_id != conf.get("core_enterprise_id"):
        raise api_error("ERR_OWNERSHIP_VIOLATION", "CoreEnterpriseUser does not own this confirmation")
    if g.user_role == "SupplierUser" and g.user_id != conf.get("supplier_id"):
        raise api_error("ERR_OWNERSHIP_VIOLATION", "SupplierUser does not own this confirmation")
    return success_envelope(conf)
