"""Contract, Certification, PaymentRequest routes."""

from datetime import date

from flask import Blueprint, request

import db as dbmod
from errors import (
    raise_err, ERR_VALIDATION, ERR_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER, ERR_SOD_VIOLATION,
    ERR_THIRD_PARTY_NOT_APPROVED, ERR_CONTRACT_NOT_ACTIVE,
    ERR_CLAUSE_SET_INCOMPLETE, ERR_CERTIFICATION_REQUIRED, ERR_CERTIFICATION_LAPSED,
    ERR_REDILIGENCE_OVERDUE, ERR_COMMISSION_CAP_EXCEEDED, ERR_ENHANCED_REVIEW_REQUIRED,
)
from middleware import require_roles, get_json_body, parse_pagination, ALL_ROLES
from response import success_object, success_list
from services.common import (
    new_id, stamp_new, touch, bump, req_str, req_int, opt_bool, req_enum,
    parse_iso_date, number_out,
)
from services import core

bp = Blueprint("contracts", __name__)


def serialize_contract(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "third_party_id": c["third_party_id"],
        "contract_status": c["contract_status"],
        "contract_value_cents": c["contract_value_cents"],
        "start_date": c["start_date"].isoformat(),
        "end_date": c["end_date"].isoformat(),
        "clause_codes": c["clause_codes"],
        "approved_payments_total_cents": c["approved_payments_total_cents"],
    }


def serialize_cert(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "third_party_id": c["third_party_id"],
        "cert_type": c["cert_type"],
        "cert_status": c["cert_status"],
        "document_ref": c["document_ref"],
        "valid_until": (c["valid_until"].isoformat() if c["valid_until"] else None),
    }


def serialize_payment(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "contract_id": p["contract_id"],
        "payment_type": p["payment_type"],
        "amount_cents": p["amount_cents"],
        "ratio_pct": number_out(p["ratio_pct"]),
        "enhanced_review_evidence": p["enhanced_review_evidence"],
        "payment_status": p["payment_status"],
        "submitted_by_user_id": p["submitted_by_user_id"],
        "approved_by_user_id": p["approved_by_user_id"],
    }


def _get_contract(contract_id):
    c = dbmod.DB["contracts"].get(contract_id)
    if c is None:
        raise_err(ERR_NOT_FOUND, "contract not found")
    return c


def _get_cert(cert_id):
    c = dbmod.DB["certifications"].get(cert_id)
    if c is None:
        raise_err(ERR_NOT_FOUND, "certification not found")
    return c


def _get_payment(payment_id):
    p = dbmod.DB["payment_requests"].get(payment_id)
    if p is None:
        raise_err(ERR_NOT_FOUND, "payment request not found")
    return p


# --- Contract ----------------------------------------------------------------------

@bp.post("/compliance/third-parties/<id>/contracts")
def create_contract(id):
    user_id, _ = require_roles(["BusinessSponsor"])
    tp = core.get_tp(id)
    body = get_json_body()
    core.ensure_not_terminal(tp["onboarding_status"], core.TP_TERMINAL, "ThirdParty")
    value = req_int(body, "contract_value_cents")
    if value <= 0:
        raise_err(ERR_VALIDATION, "contract_value_cents must be > 0")
    start = parse_iso_date(req_str(body, "start_date"), "start_date")
    end = parse_iso_date(req_str(body, "end_date"), "end_date")
    if end <= start:
        raise_err(ERR_VALIDATION, "end_date must be later than start_date")
    if tp["onboarding_status"] != "APPROVED":
        raise_err(ERR_THIRD_PARTY_NOT_APPROVED, "third party is not APPROVED")
    rec = stamp_new({
        "id": new_id(),
        "third_party_id": tp["id"],
        "contract_status": "DRAFT",
        "contract_value_cents": value,
        "start_date": start,
        "end_date": end,
        "clause_codes": [],
        "approved_payments_total_cents": 0,
    })
    dbmod.DB["contracts"][rec["id"]] = rec
    return success_object(serialize_contract(rec), 201)


@bp.post("/compliance/contracts/<contract_id>/attach-clauses")
def attach_clauses(contract_id):
    user_id, _ = require_roles(["BusinessSponsor"])
    c = _get_contract(contract_id)
    tp = core.get_tp(c["third_party_id"])
    body = get_json_body()
    core.ensure_not_terminal(c["contract_status"], core.CONTRACT_TERMINAL, "Contract")
    core.ensure_transition(c["contract_status"], {"DRAFT"}, "Contract")
    codes = body.get("clause_codes")
    if not isinstance(codes, list) or not all(isinstance(x, str) for x in codes):
        raise_err(ERR_VALIDATION, "clause_codes must be an array of strings")
    if tp["onboarding_status"] != "APPROVED":
        raise_err(ERR_THIRD_PARTY_NOT_APPROVED, "third party is not APPROVED")
    c["clause_codes"] = list(codes)
    c["contract_status"] = "PENDING_CLAUSES"
    touch(c)
    return success_object(serialize_contract(c))


@bp.post("/compliance/contracts/<contract_id>/activate")
def activate_contract(contract_id):
    require_roles(["ComplianceOfficer"])
    c = _get_contract(contract_id)
    tp = core.get_tp(c["third_party_id"])
    core.ensure_not_terminal(c["contract_status"], core.CONTRACT_TERMINAL, "Contract")
    core.ensure_transition(c["contract_status"], {"PENDING_CLAUSES"}, "Contract")
    # clause-set check (business constraint, priority 8) before referential gates
    snapshot = tp.get("approval_tier_snapshot") or "LOW"
    required = core.REQUIRED_CLAUSES[snapshot]
    if not required.issubset(set(c["clause_codes"])):
        raise_err(ERR_CLAUSE_SET_INCOMPLETE, "clause set does not cover the required set for the approval tier")
    if tp["onboarding_status"] != "APPROVED":
        raise_err(ERR_THIRD_PARTY_NOT_APPROVED, "third party is not APPROVED")
    if not core.has_verified_certification(tp["id"]):
        raise_err(ERR_CERTIFICATION_REQUIRED, "no VERIFIED certification exists for the third party")
    if core.has_overdue_cycle(tp["id"]):
        raise_err(ERR_REDILIGENCE_OVERDUE, "a re-diligence cycle is OVERDUE")
    c["contract_status"] = "ACTIVE"
    touch(c)
    return success_object(serialize_contract(c))


@bp.get("/compliance/contracts/<contract_id>")
def get_contract(contract_id):
    require_roles(ALL_ROLES)
    c = _get_contract(contract_id)
    return success_object(serialize_contract(c))


@bp.get("/compliance/third-parties/<id>/contracts")
def list_contracts(id):
    require_roles(ALL_ROLES)
    core.get_tp(id)
    limit, offset = parse_pagination()
    status_f = request.args.get("contract_status")
    rows = core.contracts_of(id)
    if status_f is not None:
        rows = [r for r in rows if r["contract_status"] == status_f]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serialize_contract(r) for r in page], total, limit, offset)


# --- Certification ------------------------------------------------------------------

@bp.post("/compliance/third-parties/<id>/certifications")
def create_certification(id):
    require_roles(["ComplianceOfficer"])
    tp = core.get_tp(id)
    body = get_json_body()
    core.ensure_not_terminal(tp["onboarding_status"], core.TP_TERMINAL, "ThirdParty")
    cert_type = req_enum(body, "cert_type", {"ANNUAL_ABAC", "CODE_OF_CONDUCT"})
    rec = stamp_new({
        "id": new_id(),
        "third_party_id": tp["id"],
        "cert_type": cert_type,
        "cert_status": "PENDING",
        "document_ref": None,
        "valid_until": None,
    })
    dbmod.DB["certifications"][rec["id"]] = rec
    return success_object(serialize_cert(rec), 201)


@bp.post("/compliance/certifications/<certification_id>/submit")
def submit_certification(certification_id):
    user_id, _ = require_roles(["BusinessSponsor"])
    cert = _get_cert(certification_id)
    tp = core.get_tp(cert["third_party_id"])
    body = get_json_body()
    core.ensure_transition(cert["cert_status"], {"PENDING", "REJECTED"}, "Certification")
    if tp["sponsor_user_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "sponsor may only submit certifications for its own third parties")
    cert["document_ref"] = req_str(body, "document_ref")
    cert["cert_status"] = "SUBMITTED"
    touch(cert)
    return success_object(serialize_cert(cert))


@bp.post("/compliance/certifications/<certification_id>/verify")
def verify_certification(certification_id):
    require_roles(["ComplianceOfficer"])
    cert = _get_cert(certification_id)
    core.ensure_transition(cert["cert_status"], {"SUBMITTED"}, "Certification")
    today = dbmod.current_date()
    cert["valid_until"] = date.fromordinal(today.toordinal() + 365)
    cert["cert_status"] = "VERIFIED"
    touch(cert)
    return success_object(serialize_cert(cert))


@bp.post("/compliance/certifications/<certification_id>/reject")
def reject_certification(certification_id):
    require_roles(["ComplianceOfficer"])
    cert = _get_cert(certification_id)
    core.ensure_transition(cert["cert_status"], {"SUBMITTED"}, "Certification")
    cert["cert_status"] = "REJECTED"
    touch(cert)
    return success_object(serialize_cert(cert))


@bp.get("/compliance/third-parties/<id>/certifications")
def list_certifications(id):
    require_roles(ALL_ROLES)
    core.get_tp(id)
    limit, offset = parse_pagination()
    status_f = request.args.get("cert_status")
    rows = core.certs_of(id)
    if status_f is not None:
        rows = [r for r in rows if r["cert_status"] == status_f]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serialize_cert(r) for r in page], total, limit, offset)


# --- PaymentRequest -------------------------------------------------------------------

@bp.post("/compliance/contracts/<id>/payment-requests")
def create_payment(id):
    user_id, _ = require_roles(["BusinessSponsor"])
    c = _get_contract(id)
    tp = core.get_tp(c["third_party_id"])
    body = get_json_body()
    core.ensure_not_terminal(c["contract_status"], core.CONTRACT_TERMINAL, "Contract")
    ptype = req_enum(body, "payment_type", {"COMMISSION", "SUCCESS_FEE", "REIMBURSEMENT"})
    amount = req_int(body, "amount_cents")
    if amount <= 0:
        raise_err(ERR_VALIDATION, "amount_cents must be > 0")
    evidence = opt_bool(body, "enhanced_review_evidence", False)
    if c["contract_status"] != "ACTIVE":
        raise_err(ERR_CONTRACT_NOT_ACTIVE, "contract is not ACTIVE")
    ratio = core.compute_ratio_pct(amount, c["contract_value_cents"])
    rec = stamp_new({
        "id": new_id(),
        "contract_id": c["id"],
        "payment_type": ptype,
        "amount_cents": amount,
        "ratio_pct": ratio,
        "enhanced_review_evidence": evidence,
        "payment_status": "SUBMITTED",
        "submitted_by_user_id": user_id,
        "approved_by_user_id": None,
    })
    dbmod.DB["payment_requests"][rec["id"]] = rec
    return success_object(serialize_payment(rec), 201)


@bp.post("/compliance/payment-requests/<payment_id>/approve")
def approve_payment(payment_id):
    user_id, _ = require_roles(["FinanceReviewer"])
    p = _get_payment(payment_id)
    c = _get_contract(p["contract_id"])
    tp = core.get_tp(c["third_party_id"])
    core.ensure_not_terminal(p["payment_status"], core.PAYMENT_TERMINAL, "PaymentRequest")
    core.ensure_transition(p["payment_status"], {"SUBMITTED"}, "PaymentRequest")
    # SoD vs submitter (priority 8) precedes the referential gates (priority 9)
    if p["submitted_by_user_id"] == user_id:
        raise_err(ERR_SOD_VIOLATION, "approver must differ from submitter")
    if c["contract_status"] != "ACTIVE":
        raise_err(ERR_CONTRACT_NOT_ACTIVE, "contract is not ACTIVE")
    if tp["onboarding_status"] != "APPROVED":
        raise_err(ERR_THIRD_PARTY_NOT_APPROVED, "third party is not APPROVED")
    if not core.has_verified_certification(tp["id"]):
        raise_err(ERR_CERTIFICATION_LAPSED, "no VERIFIED (non-lapsed) certification exists")
    # fiscal brackets (priority 10): hard cap strictly, then evidence band
    policy = core.require_active_policy()
    verdict = core.evaluate_commission_bracket(p, c, tp, policy)
    if verdict == "BLOCKED_ONLY":
        raise_err(ERR_COMMISSION_CAP_EXCEEDED, "ratio exceeds the commission hard cap")
    if verdict == "EVIDENCE_REQUIRED" and not p["enhanced_review_evidence"]:
        raise_err(ERR_ENHANCED_REVIEW_REQUIRED, "enhanced review evidence is required for this ratio band")

    p["payment_status"] = "APPROVED"
    p["approved_by_user_id"] = user_id
    touch(p)
    c["approved_payments_total_cents"] += p["amount_cents"]
    touch(c)
    return success_object(serialize_payment(p))


@bp.post("/compliance/payment-requests/<payment_id>/block")
def block_payment(payment_id):
    require_roles(["FinanceReviewer"])
    p = _get_payment(payment_id)
    core.ensure_not_terminal(p["payment_status"], core.PAYMENT_TERMINAL, "PaymentRequest")
    core.ensure_transition(p["payment_status"], {"SUBMITTED"}, "PaymentRequest")
    p["payment_status"] = "BLOCKED"
    touch(p)
    return success_object(serialize_payment(p))


@bp.post("/compliance/payment-requests/<payment_id>/reverse")
def reverse_payment(payment_id):
    user_id, _ = require_roles(["FinanceReviewer"])
    p = _get_payment(payment_id)
    c = _get_contract(p["contract_id"])
    core.ensure_not_terminal(p["payment_status"], core.PAYMENT_TERMINAL, "PaymentRequest")
    core.ensure_transition(p["payment_status"], {"APPROVED"}, "PaymentRequest")
    if p["approved_by_user_id"] == user_id:
        raise_err(ERR_SOD_VIOLATION, "reverser must differ from approver")
    p["payment_status"] = "REVERSED"
    touch(p)
    c["approved_payments_total_cents"] -= p["amount_cents"]
    if c["approved_payments_total_cents"] < 0:
        c["approved_payments_total_cents"] = 0
    touch(c)
    return success_object(serialize_payment(p))


@bp.get("/compliance/contracts/<id>/payment-requests")
def list_payments(id):
    require_roles(ALL_ROLES)
    _get_contract(id)
    limit, offset = parse_pagination()
    status_f = request.args.get("payment_status")
    rows = core.payments_of_contract(id)
    if status_f is not None:
        rows = [r for r in rows if r["payment_status"] == status_f]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serialize_payment(r) for r in page], total, limit, offset)
