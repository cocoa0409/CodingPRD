"""Contract endpoints (PRD §3.6)."""

from __future__ import annotations

from flask import Blueprint, g, jsonify

from audit import append_audit
from db import db, stamp_create, stamp_update, serialize, serialize_list, order_by_created_then_seq
from errors import err
from middleware import enforce_role, require_roles
from response import success_object
from services.calculations import generate_payment_schedule
from services.lookups import (
    find_clause_template,
    find_contract,
    find_purchase_order,
)
from validate import (
    get_json_body,
    require_enum,
    require_fields,
    require_list,
    require_string,
)

bp = Blueprint("contracts", __name__)

PAYMENT_TERMS = {"ADVANCE", "ON_DELIVERY", "NET_N_DAYS", "INSTALLMENT"}
SIGNER_ROLES = {"Buyer", "Supplier"}


def _validate_payment_terms(terms_type: str, params: dict) -> None:
    if not isinstance(params, dict):
        raise err("ERR_VALIDATION", "payment_terms_params must be an object.")
    if terms_type == "NET_N_DAYS":
        net_days = params.get("net_days")
        if not isinstance(net_days, int) or isinstance(net_days, bool) or net_days < 0:
            raise err("ERR_VALIDATION", "payment_terms_params.net_days must be a non-negative integer.")
    elif terms_type == "INSTALLMENT":
        sched = params.get("schedule")
        if not isinstance(sched, list) or not sched:
            raise err("ERR_VALIDATION", "payment_terms_params.schedule must be a non-empty list.")
        total_pct = 0
        for item in sched:
            if not isinstance(item, dict):
                raise err("ERR_VALIDATION", "schedule items must be objects.")
            pct = item.get("percent")
            off = item.get("offset_days")
            if not isinstance(pct, int) or isinstance(pct, bool) or pct < 0:
                raise err("ERR_VALIDATION", "percent must be a non-negative integer.")
            if not isinstance(off, int) or isinstance(off, bool) or off < 0:
                raise err("ERR_VALIDATION", "offset_days must be a non-negative integer.")
            total_pct += pct
        if total_pct != 100:
            raise err("ERR_VALIDATION", "INSTALLMENT percents must sum to exactly 100.")


def _write_version(contract: dict, change_reason: str) -> dict:
    """Append a ContractVersion snapshot and an audit entry."""
    snapshot = {
        "contract_id": contract["id"],
        "version_number": contract["current_version"],
        "clause_template_ids_snapshot": list(contract.get("clause_template_ids") or []),
        "payment_terms_snapshot": {
            "payment_terms_type": contract.get("payment_terms_type"),
            "payment_terms_params": contract.get("payment_terms_params"),
        },
        "change_reason": change_reason,
    }
    stamp_create(snapshot, common=False)
    db.contract_versions[snapshot["id"]] = snapshot
    append_audit(
        action="CONTRACT_VERSION_CREATED",
        entity_type="Contract",
        entity_id=contract["id"],
        payload={"version_number": snapshot["version_number"], "change_reason": change_reason},
    )
    return snapshot


@bp.post("/contracts")
@require_roles("Buyer")
def create_contract():
    body = get_json_body()
    require_fields(body, [
        "purchase_order_id", "clause_template_ids",
        "payment_terms_type", "payment_terms_params", "parties_required",
    ])
    po_id = require_string(body["purchase_order_id"], "purchase_order_id")
    po = db.purchase_orders.get(po_id)
    if po is None:
        raise err("ERR_VALIDATION", "purchase_order_id does not exist.")
    if po["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "PurchaseOrder is not APPROVED.")
    # Unique contract per PO
    for c in db.contracts.values():
        if c.get("purchase_order_id") == po_id:
            raise err("ERR_CONTRACT_ALREADY_EXISTS",
                      "A Contract already exists for this PurchaseOrder.")

    template_ids = require_list(body["clause_template_ids"], "clause_template_ids", allow_empty=False)
    for tid in template_ids:
        if not isinstance(tid, str):
            raise err("ERR_VALIDATION", "clause_template_ids items must be strings.")
        # Existence check on each
        if tid not in db.clause_templates:
            raise err("ERR_VALIDATION", f"ClauseTemplate {tid} does not exist.")

    terms_type = body["payment_terms_type"]
    require_enum(terms_type, PAYMENT_TERMS, "payment_terms_type")
    terms_params = body["payment_terms_params"]
    _validate_payment_terms(terms_type, terms_params)

    parties = require_list(body["parties_required"], "parties_required", allow_empty=False)
    for p in parties:
        require_enum(p, SIGNER_ROLES, "parties_required[]")

    contract = {
        "purchase_order_id": po_id,
        "clause_template_ids": list(template_ids),
        "payment_terms_type": terms_type,
        "payment_terms_params": terms_params,
        "parties_required": list(parties),
        "signatures": [],
        "current_version": 1,
        "status": "DRAFTING",
    }
    stamp_create(contract, common=True)
    db.contracts[contract["id"]] = contract

    # Initial v1 snapshot (PRD §3.6 first paragraph)
    _write_version(contract, change_reason=body.get("change_reason") or "Initial draft")

    return jsonify(success_object(serialize(contract))), 201


@bp.post("/contracts/<rid>/submit-for-review")
@require_roles("Buyer")
def submit_for_review(rid: str):
    c = find_contract(rid)
    enforce_role()
    if c["status"] != "DRAFTING":
        raise err("ERR_INVALID_STATE", "Contract is not DRAFTING.")
    po = db.purchase_orders.get(c["purchase_order_id"])
    if po is None or po["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Bound PO is not APPROVED.")
    if not c.get("clause_template_ids"):
        raise err("ERR_VALIDATION", "clause_template_ids must be non-empty.")
    # Active templates only
    for tid in c["clause_template_ids"]:
        t = db.clause_templates.get(tid)
        if t is None:
            raise err("ERR_VALIDATION", f"ClauseTemplate {tid} not found.")
        if not t.get("is_active"):
            raise err("ERR_CLAUSE_TEMPLATE_INACTIVE",
                      f"ClauseTemplate {tid} is not active.")
    c["status"] = "IN_REVIEW"
    stamp_update(c)
    return jsonify(success_object(serialize(c))), 200


@bp.post("/contracts/<rid>/finalize-review")
@require_roles("LegalApprover")
def finalize_review(rid: str):
    c = find_contract(rid)
    enforce_role()
    if c["status"] != "IN_REVIEW":
        raise err("ERR_INVALID_STATE", "Contract is not IN_REVIEW.")
    c["status"] = "AWAITING_SIGNATURE"
    stamp_update(c)
    return jsonify(success_object(serialize(c))), 200


@bp.post("/contracts/<rid>/amend")
@require_roles("Buyer")
def amend_contract(rid: str):
    c = find_contract(rid)
    enforce_role()
    if c["status"] not in ("IN_REVIEW", "AWAITING_SIGNATURE"):
        raise err("ERR_INVALID_STATE", "Contract cannot be amended in current state.")
    body = get_json_body()
    change_reason = body.get("change_reason")
    if not isinstance(change_reason, str) or change_reason.strip() == "":
        raise err("ERR_VALIDATION", "change_reason must be a non-empty string.")

    new_clauses = body.get("clause_template_ids")
    if new_clauses is not None:
        if not isinstance(new_clauses, list) or not new_clauses:
            raise err("ERR_VALIDATION", "clause_template_ids must be a non-empty list.")
        for tid in new_clauses:
            if not isinstance(tid, str) or tid not in db.clause_templates:
                raise err("ERR_VALIDATION", f"ClauseTemplate {tid} not found.")
        c["clause_template_ids"] = list(new_clauses)

    new_terms_type = body.get("payment_terms_type")
    new_terms_params = body.get("payment_terms_params")
    if new_terms_type is not None:
        require_enum(new_terms_type, PAYMENT_TERMS, "payment_terms_type")
        c["payment_terms_type"] = new_terms_type
    if new_terms_params is not None:
        _validate_payment_terms(c["payment_terms_type"], new_terms_params)
        c["payment_terms_params"] = new_terms_params

    # Bump version + reset to DRAFTING + clear signatures (per PRD §3.6 last
    # paragraph of the "Two outcomes" section)
    c["current_version"] = int(c.get("current_version", 1)) + 1
    c["signatures"] = []
    c["status"] = "DRAFTING"
    stamp_update(c)

    # New ContractVersion snapshot
    _write_version(c, change_reason=change_reason)
    append_audit(
        action="CONTRACT_AMENDED",
        entity_type="Contract",
        entity_id=c["id"],
        payload={"version_number": c["current_version"], "change_reason": change_reason},
    )

    return jsonify(success_object(serialize(c))), 200


@bp.post("/contracts/<rid>/sign")
@require_roles("Buyer", "Supplier")
def sign_contract(rid: str):
    c = find_contract(rid)
    enforce_role()
    body = get_json_body()
    require_fields(body, ["role", "signature_ref"])
    role = body["role"]
    require_enum(role, SIGNER_ROLES, "role")
    signature_ref = require_string(body["signature_ref"], "signature_ref")

    if c["status"] != "AWAITING_SIGNATURE":
        raise err("ERR_INVALID_STATE", "Contract is not AWAITING_SIGNATURE.")

    # Caller's role must align with signer role
    if g.user_role != role:
        raise err("ERR_FORBIDDEN", "Caller's role does not match signer role.")

    # Supplier identity check (PRD §2.1)
    if role == "Supplier":
        po = db.purchase_orders.get(c["purchase_order_id"])
        if po is None:
            raise err("ERR_NOT_FOUND", "PurchaseOrder not found.")
        if g.user_id != po.get("supplier_id"):
            raise err("ERR_FORBIDDEN",
                      "Supplier signer X-User-ID does not match PO.supplier_id.")

    # Role must be required by the contract's parties_required
    if role not in (c.get("parties_required") or []):
        raise err("ERR_VALIDATION", f"role {role} is not required by this contract.")

    # Unique role per contract
    for sig in c.get("signatures") or []:
        if sig.get("role") == role:
            raise err("ERR_SIGNATURE_ALREADY_COLLECTED",
                      f"A signature for role {role} has already been collected.")

    sig = {
        "role": role,
        "user_id": g.user_id,
        "signed_at": db.now_iso(),
        "signature_ref": signature_ref,
    }
    c["signatures"].append(sig)
    stamp_update(c)
    append_audit(
        action="CONTRACT_SIGNED",
        entity_type="Contract",
        entity_id=c["id"],
        payload={"role": role, "user_id": g.user_id, "signature_ref": signature_ref},
    )

    # If every required role now has a signature, move to EXECUTED
    collected = {s.get("role") for s in c["signatures"]}
    required = set(c.get("parties_required") or [])
    if required.issubset(collected):
        c["status"] = "EXECUTED"
        stamp_update(c)
        # Cascade: PO -> CONTRACTED
        po = db.purchase_orders.get(c["purchase_order_id"])
        if po is not None and po["status"] == "APPROVED":
            po["status"] = "CONTRACTED"
            stamp_update(po)
        # Generate payment schedule
        if po is not None:
            requirement = db.requirements.get(po["requirement_id"])
            if requirement is not None:
                generate_payment_schedule(c, po, requirement)

    return jsonify(success_object(serialize(c))), 200


@bp.post("/contracts/<rid>/terminate")
@require_roles("GeneralManager")
def terminate_contract(rid: str):
    c = find_contract(rid)
    enforce_role()
    body = get_json_body()
    reason = require_string(body.get("reason", ""), "reason")
    if c["status"] != "EXECUTED":
        raise err("ERR_INVALID_STATE", "Contract is not EXECUTED.")
    po = db.purchase_orders.get(c["purchase_order_id"])
    if po is None or po["status"] not in ("CONTRACTED", "FULFILLED"):
        raise err("ERR_INVALID_STATE", "Bound PO is not CONTRACTED/FULFILLED.")

    # Cancel every PENDING PaymentSchedule on this PO
    unpaid_balance = 0
    for sch in db.payment_schedules.values():
        if sch.get("purchase_order_id") == po["id"] and sch.get("status") == "PENDING":
            unpaid_balance += int(sch.get("amount_cents", 0))
            sch["status"] = "CANCELLED"

    # Release commitment for unpaid_balance (PRD §3.6 last paragraph)
    ba = db.budget_accounts.get(po["budget_account_id"])
    if ba is not None and unpaid_balance > 0:
        ba["committed_amount_cents"] -= unpaid_balance
        stamp_update(ba)

    c["status"] = "TERMINATED"
    stamp_update(c)
    return jsonify(success_object(serialize(c))), 200


@bp.get("/contracts/<rid>")
@require_roles("Buyer", "Supplier", "LegalApprover", "FinanceApprover", "GeneralManager")
def get_contract(rid: str):
    c = find_contract(rid)
    enforce_role()
    # Supplier role: must own the underlying PO
    if g.user_role == "Supplier":
        po = db.purchase_orders.get(c["purchase_order_id"])
        if po is None or g.user_id != po.get("supplier_id"):
            raise err("ERR_FORBIDDEN", "Supplier may only view their own contracts.")
    return jsonify(success_object(serialize(c))), 200


@bp.get("/contracts/<rid>/versions")
@require_roles("Buyer", "Supplier", "LegalApprover", "FinanceApprover", "GeneralManager")
def list_contract_versions(rid: str):
    c = find_contract(rid)
    enforce_role()
    if g.user_role == "Supplier":
        po = db.purchase_orders.get(c["purchase_order_id"])
        if po is None or g.user_id != po.get("supplier_id"):
            raise err("ERR_FORBIDDEN", "Supplier may only view their own contracts.")
    versions = [v for v in db.contract_versions.values() if v.get("contract_id") == rid]
    versions = sorted(versions, key=lambda v: v.get("version_number", 0))
    return jsonify(success_object(serialize_list(versions))), 200
