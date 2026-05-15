"""Receivable endpoints (PRD §3.4)."""
from __future__ import annotations

from flask import Blueprint, g, request

from ..auth import require_auth
from ..constants import CENTRAL_REGISTRY_THRESHOLD_CENTS
from ..errors import api_error
from ..response import list_envelope, success_envelope
from ..store import store
from ..utils import (
    check_version,
    get_json_body,
    page_slice,
    parse_pagination,
    require_str,
)

bp = Blueprint("receivables", __name__, url_prefix="/scf/receivables")

READ_ROLES = ("SupplierUser", "RiskReviewer", "CreditApprover", "PlatformAdmin")


# ---- POST /scf/receivables ----
@bp.post("")
@require_auth(["SupplierUser"])
def register_receivable():
    body = get_json_body()
    confirmation_id = require_str(body, "confirmation_id")
    invoice_doc_id = require_str(body, "invoice_doc_id")
    contract_doc_id = require_str(body, "contract_doc_id")

    conf = store.payable_confirmations.get(confirmation_id)
    if conf is None:
        raise api_error("ERR_REFERENCED_NOT_FOUND", "confirmation_id not found")

    # Ownership: SupplierUser is the supplier on the confirmation
    if g.user_id != conf.get("supplier_id"):
        raise api_error("ERR_OWNERSHIP_VIOLATION", "SupplierUser does not own this confirmation")
    supplier = store.suppliers.get(conf["supplier_id"])
    if supplier and supplier.get("status") == "BLACKLISTED":
        raise api_error("ERR_SUPPLIER_BLACKLISTED", "Supplier is BLACKLISTED")

    if conf.get("status") != "CONFIRMED":
        raise api_error("ERR_INVALID_STATE", "Confirmation must be CONFIRMED")

    # Uniqueness: at most one Receivable per confirmation_id
    for existing in store.receivables.values():
        if existing.get("confirmation_id") == confirmation_id:
            raise api_error("ERR_DOUBLE_FINANCING", "Receivable already exists for this confirmation")

    amount_cents = int(conf["amount_cents"])
    central_required = amount_cents >= CENTRAL_REGISTRY_THRESHOLD_CENTS

    with store.lock:
        payload = {
            "confirmation_id": confirmation_id,
            "supplier_id": conf["supplier_id"],
            "core_enterprise_id": conf["core_enterprise_id"],
            "amount_cents": amount_cents,
            "due_date": conf["due_date"],
            "invoice_doc_id": invoice_doc_id,
            "contract_doc_id": contract_doc_id,
            "status": "REGISTERED",
            "central_registry_required": central_required,
            "central_registry_filing_no": None,
        }
        store.stamp_create(payload)
        store.receivables[payload["id"]] = payload
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="Receivable",
            entity_id=payload["id"],
            action="REGISTER",
            amount_cents=amount_cents,
        )
    return success_envelope(payload, status=201)


# ---- POST /scf/receivables/{id}/central-registry-file ----
@bp.post("/<rid>/central-registry-file")
@require_auth(["PlatformAdmin"])
def central_registry_file(rid):
    receivable = store.receivables.get(rid)
    if receivable is None:
        raise api_error("ERR_NOT_FOUND", "Receivable not found")
    body = get_json_body()
    check_version(body, receivable)
    filing_no = require_str(body, "central_registry_filing_no")

    with store.lock:
        receivable["central_registry_filing_no"] = filing_no
        store.stamp_update(receivable)
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="Receivable",
            entity_id=receivable["id"],
            action="CENTRAL_REGISTRY_FILE",
        )
    return success_envelope(receivable)


# ---- POST /scf/receivables/{id}/pledge ----
@bp.post("/<rid>/pledge")
@require_auth(["SupplierUser"])
def pledge_receivable(rid):
    receivable = store.receivables.get(rid)
    if receivable is None:
        raise api_error("ERR_NOT_FOUND", "Receivable not found")
    if g.user_id != receivable.get("supplier_id"):
        raise api_error("ERR_OWNERSHIP_VIOLATION", "SupplierUser does not own this receivable")
    supplier = store.suppliers.get(receivable["supplier_id"])
    if supplier and supplier.get("status") == "BLACKLISTED":
        raise api_error("ERR_SUPPLIER_BLACKLISTED", "Supplier is BLACKLISTED")
    body = get_json_body()
    if receivable.get("status") != "REGISTERED":
        check_version(body, receivable)
        raise api_error("ERR_INVALID_STATE", "Receivable is not REGISTERED")
    check_version(body, receivable)
    if receivable.get("central_registry_required") and not receivable.get("central_registry_filing_no"):
        raise api_error("ERR_CENTRAL_REGISTRY_FILING_REQUIRED", "Central-registry filing required")
    with store.lock:
        receivable["status"] = "PLEDGED"
        store.stamp_update(receivable)
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="Receivable",
            entity_id=receivable["id"],
            action="REGISTER",
        )
    return success_envelope(receivable)


# ---- POST /scf/receivables/{id}/transfer ----
@bp.post("/<rid>/transfer")
@require_auth(["SupplierUser"])
def transfer_receivable(rid):
    receivable = store.receivables.get(rid)
    if receivable is None:
        raise api_error("ERR_NOT_FOUND", "Receivable not found")
    if g.user_id != receivable.get("supplier_id"):
        raise api_error("ERR_OWNERSHIP_VIOLATION", "SupplierUser does not own this receivable")
    supplier = store.suppliers.get(receivable["supplier_id"])
    if supplier and supplier.get("status") == "BLACKLISTED":
        raise api_error("ERR_SUPPLIER_BLACKLISTED", "Supplier is BLACKLISTED")
    body = get_json_body()
    if receivable.get("status") != "REGISTERED":
        check_version(body, receivable)
        raise api_error("ERR_INVALID_STATE", "Receivable is not REGISTERED")
    check_version(body, receivable)
    new_supplier_id = require_str(body, "new_supplier_id")
    if new_supplier_id not in store.suppliers:
        raise api_error("ERR_REFERENCED_NOT_FOUND", "new_supplier_id not found")
    if receivable.get("central_registry_required") and not receivable.get("central_registry_filing_no"):
        raise api_error("ERR_CENTRAL_REGISTRY_FILING_REQUIRED", "Central-registry filing required")

    # No active financing application beyond DRAFT
    for app in store.financing_applications.values():
        if app.get("receivable_id") != receivable["id"]:
            continue
        if app.get("status") not in ("DRAFT", "REJECTED", "CANCELLED"):
            raise api_error("ERR_INVALID_STATE", "Receivable has an active financing application")

    with store.lock:
        receivable["status"] = "TRANSFERRED"
        receivable["supplier_id"] = new_supplier_id
        store.stamp_update(receivable)
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="Receivable",
            entity_id=receivable["id"],
            action="REGISTER",
        )
    return success_envelope(receivable)


# ---- GET /scf/receivables/{id} ----
@bp.get("/<rid>")
@require_auth(READ_ROLES)
def get_receivable(rid):
    receivable = store.receivables.get(rid)
    if receivable is None:
        raise api_error("ERR_NOT_FOUND", "Receivable not found")
    if g.user_role == "SupplierUser" and g.user_id != receivable.get("supplier_id"):
        raise api_error("ERR_OWNERSHIP_VIOLATION", "SupplierUser does not own this receivable")
    return success_envelope(receivable)


# ---- GET /scf/receivables ----
@bp.get("")
@require_auth(READ_ROLES)
def list_receivables():
    limit, offset = parse_pagination()
    supplier_id = request.args.get("supplier_id")
    status = request.args.get("status")
    cr_required = request.args.get("central_registry_required")

    items = list(store.receivables.values())
    if supplier_id:
        items = [r for r in items if r.get("supplier_id") == supplier_id]
    if status:
        items = [r for r in items if r.get("status") == status]
    if cr_required is not None:
        truthy = cr_required.lower() in ("true", "1", "yes")
        items = [r for r in items if bool(r.get("central_registry_required")) == truthy]

    if g.user_role == "SupplierUser":
        items = [r for r in items if r.get("supplier_id") == g.user_id]
    items.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    page, total = page_slice(items, limit, offset)
    return list_envelope(page, total, limit, offset)
