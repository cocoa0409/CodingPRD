"""Contract routes (CRUD + lifecycle transitions)."""
from flask import Blueprint, request, g

import db
from errors import (
    raise_error,
    ERR_QUOTE_VENDOR_MISMATCH,
    ERR_CONTRACT_NOT_IN_DRAFT,
    ERR_CONTRACT_NOT_NEGOTIATING,
    ERR_CONTRACT_NOT_SIGNED,
    ERR_QUOTE_NOT_AVAILABLE,
    ERR_QUOTE_EXPIRED,
    ERR_PROJECT_NOT_IN_PLANNING,
    ERR_BUDGET_OVERCOMMITTED,
    ERR_NOT_OWNING_VENDOR,
    ERR_ESIGN_NOT_COMPLETE,
)
from middleware import require_roles, check_planner_owns_project
from response import success, list_response, parse_pagination
from services.lookup import (
    get_project,
    get_vendor,
    get_quote,
    get_contract,
    assert_project_not_terminal,
)
from services.budget import recompute_project_ledger, soft_warning_threshold
from services.audit import append_audit


bp = Blueprint("contracts", __name__)


def _terminate_contract_cascade(project: dict, contract: dict):
    """Common cascade for contract termination from any non-terminal state."""
    prior = contract["contract_status"]
    # Bound Quote -> WITHDRAWN if currently OFFERED or BOUND
    quote = db.quotes.get(contract["quote_id"])
    if quote and quote["status"] in ("OFFERED", "BOUND", "DRAFT"):
        # DRAFT is also withdrawn per cascade
        quote["status"] = "WITHDRAWN"
        db.bump(quote)
    # If SIGNED or ACCEPTED: delete TimelineSlots for this vendor on this project
    if prior in ("SIGNED", "ACCEPTED"):
        to_delete = [
            s_id for s_id, s in db.timeline_slots.items()
            if s["project_id"] == project["id"] and s.get("vendor_id") == contract["vendor_id"]
        ]
        for s_id in to_delete:
            del db.timeline_slots[s_id]
    # If ACCEPTED: reset settlement DRAFT/VENDOR_CONFIRMED to DRAFT, clear confirmed_by_vendor_at
    if prior == "ACCEPTED":
        for s in db.settlements.values():
            if s["contract_id"] == contract["id"] and s["status"] in ("DRAFT", "VENDOR_CONFIRMED"):
                s["status"] = "DRAFT"
                s["confirmed_by_vendor_at"] = None
                db.bump(s)
    # Set contract status -> TERMINATED
    contract["contract_status"] = "TERMINATED"
    db.bump(contract)
    # Recompute project ledger
    recompute_project_ledger(project)
    # Append audit (only when from a non-DRAFT state we still log per PRD §3.1 cascade,
    # but the PRD says 'Each contract termination during cascade writes its own AuditEntry'
    # So always log on terminate.)
    append_audit(
        project_id=project["id"],
        subject_type="CONTRACT",
        subject_id=contract["id"],
        event_kind="CONTRACT_TERMINATED",
        payload={
            "from_status": prior,
            "to_status": "TERMINATED",
            "vendor_id": contract["vendor_id"],
            "quote_id": contract["quote_id"],
        },
    )


@bp.post("/wedding-projects/<project_id>/contracts")
def create_contract(project_id):
    require_roles("Planner")
    p = get_project(project_id)
    check_planner_owns_project(p)
    assert_project_not_terminal(p)
    body = request.get_json(silent=True) or {}
    vendor_id = body.get("vendor_id")
    quote_id = body.get("quote_id")
    vendor = get_vendor(vendor_id)
    # Quote existence is checked by get_quote, but it must belong to vendor
    q = db.quotes.get(quote_id)
    if not q:
        from errors import ERR_QUOTE_NOT_FOUND
        raise_error(ERR_QUOTE_NOT_FOUND, "Quote not found")
    if q["vendor_id"] != vendor_id:
        raise_error(ERR_QUOTE_VENDOR_MISMATCH, "Quote does not belong to vendor")
    contract = {
        "project_id": project_id,
        "vendor_id": vendor_id,
        "quote_id": quote_id,
        "pinned_quote_version": None,
        "pinned_amount_cents": 0,
        "contract_status": "DRAFT",
        "payment_status": "UNPAID",
        "e_sign_envelope_id": None,
        "negotiation_round": 0,
    }
    db.add_common_create(contract)
    db.contracts[contract["id"]] = contract
    return success(contract, status=201)


@bp.get("/wedding-projects/<project_id>/contracts")
def list_contracts(project_id):
    require_roles("Planner", "Auditor", "Couple")
    p = get_project(project_id)
    if g.user_role == "Planner":
        check_planner_owns_project(p)
    limit, offset = parse_pagination(request.args)
    cs = request.args.get("contract_status")
    ps = request.args.get("payment_status")
    items = [c for c in db.contracts.values() if c["project_id"] == project_id]
    if cs:
        items = [c for c in items if c["contract_status"] == cs]
    if ps:
        items = [c for c in items if c["payment_status"] == ps]
    items.sort(key=lambda c: c["created_at"])
    return list_response(items, limit, offset)


@bp.get("/wedding-projects/<project_id>/contracts/<contract_id>")
def get_contract_route(project_id, contract_id):
    require_roles("Planner", "Auditor", "Couple", "VendorRep")
    p = get_project(project_id)
    c = get_contract(project_id, contract_id)
    if g.user_role == "Planner":
        check_planner_owns_project(p)
    if g.user_role == "VendorRep":
        if g.user_id != c["vendor_id"]:
            raise_error(ERR_NOT_OWNING_VENDOR, "VendorRep does not own this contract's vendor")
    return success(c)


@bp.post("/wedding-projects/<project_id>/contracts/<contract_id>/send-for-negotiation")
def send_for_negotiation(project_id, contract_id):
    require_roles("Planner")
    p = get_project(project_id)
    check_planner_owns_project(p)
    assert_project_not_terminal(p)
    c = get_contract(project_id, contract_id)
    if c["contract_status"] != "DRAFT":
        raise_error(ERR_CONTRACT_NOT_IN_DRAFT, "Contract must be DRAFT")
    quote = db.quotes.get(c["quote_id"])
    if not quote or quote["status"] not in ("DRAFT", "OFFERED"):
        raise_error(ERR_QUOTE_NOT_AVAILABLE, "Quote must be DRAFT or OFFERED")
    c["contract_status"] = "NEGOTIATING"
    db.bump(c)
    if quote["status"] == "DRAFT":
        quote["status"] = "OFFERED"
        db.bump(quote)
    return success(c)


@bp.post("/wedding-projects/<project_id>/contracts/<contract_id>/revise")
def revise_contract(project_id, contract_id):
    require_roles("VendorRep")
    p = get_project(project_id)
    assert_project_not_terminal(p)
    c = get_contract(project_id, contract_id)
    # Vendor ownership check
    if g.user_id != c["vendor_id"]:
        raise_error(ERR_NOT_OWNING_VENDOR, "VendorRep does not own bound vendor")
    if c["contract_status"] != "NEGOTIATING":
        raise_error(ERR_CONTRACT_NOT_NEGOTIATING, "Contract must be NEGOTIATING")
    c["contract_status"] = "DRAFT"
    c["negotiation_round"] = int(c["negotiation_round"]) + 1
    db.bump(c)
    quote = db.quotes.get(c["quote_id"])
    if quote and quote["status"] == "OFFERED":
        quote["status"] = "DRAFT"
        db.bump(quote)
    return success(c)


@bp.post("/wedding-projects/<project_id>/contracts/<contract_id>/sign")
def sign_contract(project_id, contract_id):
    require_roles("Planner")
    p = get_project(project_id)
    check_planner_owns_project(p)
    assert_project_not_terminal(p)
    c = get_contract(project_id, contract_id)
    if c["contract_status"] != "NEGOTIATING":
        raise_error(ERR_CONTRACT_NOT_NEGOTIATING, "Contract must be NEGOTIATING")
    quote = db.quotes.get(c["quote_id"])
    if not quote or quote["status"] != "OFFERED":
        raise_error(ERR_QUOTE_NOT_AVAILABLE, "Quote must be OFFERED to sign")
    if db.now_clock() >= int(quote["valid_until"]):
        raise_error(ERR_QUOTE_EXPIRED, "Quote has expired")
    if p["status"] != "PLANNING":
        raise_error(ERR_PROJECT_NOT_IN_PLANNING, "Project must be PLANNING to sign contracts")
    if int(p["budget_balance_cents"]) - int(quote["amount_cents"]) < 0:
        raise_error(ERR_BUDGET_OVERCOMMITTED, "Signing would exceed budget")
    # Pin
    c["pinned_quote_version"] = int(quote["version"])
    c["pinned_amount_cents"] = int(quote["amount_cents"])
    c["contract_status"] = "SIGNED"
    # Dispatch e-sign envelope
    envelope_id = "env_" + db.gen_id()
    c["e_sign_envelope_id"] = envelope_id
    db.bump(c)
    # Quote -> BOUND
    quote["status"] = "BOUND"
    db.bump(quote)
    # Recompute ledger
    recompute_project_ledger(p)
    # Soft overspend warning
    threshold = soft_warning_threshold(p)
    if int(p["provisional_committed_cents"]) >= threshold:
        append_audit(
            project_id=p["id"],
            subject_type="CONTRACT",
            subject_id=c["id"],
            event_kind="OVERSPEND_WARNING_RAISED",
            payload={
                "provisional_committed_cents": p["provisional_committed_cents"],
                "threshold": threshold,
                "total_budget_cents": p["total_budget_cents"],
            },
        )
    return success(c)


@bp.post("/wedding-projects/<project_id>/contracts/<contract_id>/accept-signature")
def accept_signature(project_id, contract_id):
    require_roles("Planner", "Auditor")
    p = get_project(project_id)
    if g.user_role == "Planner":
        check_planner_owns_project(p)
    assert_project_not_terminal(p)
    c = get_contract(project_id, contract_id)
    if c["contract_status"] != "SIGNED":
        raise_error(ERR_CONTRACT_NOT_SIGNED, "Contract must be SIGNED")
    envelope_id = c.get("e_sign_envelope_id")
    if not envelope_id or envelope_id not in db.esign_completed_envelope_ids:
        raise_error(ERR_ESIGN_NOT_COMPLETE, "ESIGN_COMPLETED event not received yet")
    c["contract_status"] = "ACCEPTED"
    db.bump(c)
    return success(c)


@bp.post("/wedding-projects/<project_id>/contracts/<contract_id>/terminate")
def terminate_contract(project_id, contract_id):
    require_roles("Planner")
    p = get_project(project_id)
    check_planner_owns_project(p)
    assert_project_not_terminal(p)
    c = get_contract(project_id, contract_id)
    if c["contract_status"] == "TERMINATED":
        raise_error(ERR_CONTRACT_NOT_IN_DRAFT, "Contract is already TERMINATED")
    _terminate_contract_cascade(p, c)
    return success(c)
