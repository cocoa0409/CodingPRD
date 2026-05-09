"""Reimbursement — submit/approve/pay with reject-rework loop and compliance pre-screen."""

from decimal import Decimal

from clock import clock
from common import (
    money_to_json,
    require_field,
    round_money,
    sort_by_created_at,
    stamp_create,
    stamp_update,
    to_decimal,
)
from db import db
from errors import (
    ERR_ATTACHMENTS_INCOMPLETE,
    ERR_BUDGET_INSUFFICIENT,
    ERR_BUDGET_ITEM_NOT_FOUND,
    ERR_BUDGET_NOT_APPROVED,
    ERR_CATEGORY_MISMATCH,
    ERR_COMPLIANCE_BLOCK,
    ERR_DEPT_DECISION_PENDING,
    ERR_DUPLICATE_INVOICE_NUMBER,
    ERR_ESCALATION_PENDING,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_INVOICE_DATE_OUT_OF_RANGE,
    ERR_INVOICE_NOT_AUTHENTIC,
    ERR_NOT_PROJECT_OWNER,
    ERR_PI_DECISION_PENDING,
    ERR_PROJECT_NOT_ACTIVE,
    ERR_PROJECT_NOT_FOUND,
    ERR_REIMBURSEMENT_NOT_FOUND,
    ERR_REJECTION_REASON_REQUIRED,
    ERR_REWORK_LIMIT_EXCEEDED,
    raise_error,
)
from services.audit_log import append_log
from services.compliance_rule import find_active_rules


VALID_CATEGORIES = {"PERSONNEL", "EQUIPMENT", "MATERIALS", "TRAVEL", "CONFERENCE", "OUTSOURCING"}


def get_reimbursement_or_404(reimbursement_id):
    r = db.reimbursements.get(reimbursement_id)
    if r is None:
        raise_error(ERR_REIMBURSEMENT_NOT_FOUND, f"reimbursement {reimbursement_id} not found")
    return r


def serialize_reimbursement(r):
    return {
        "id": r["id"],
        "project_id": r["project_id"],
        "budget_item_id": r["budget_item_id"],
        "expense_category": r["expense_category"],
        "amount": money_to_json(r["amount"]),
        "invoice_number": r["invoice_number"],
        "invoice_date": r["invoice_date"],
        "invoice_authenticated": r["invoice_authenticated"],
        "attachments": list(r.get("attachments") or []),
        "vendor_id": r["vendor_id"],
        "pi_decision": r["pi_decision"],
        "dept_decision": r["dept_decision"],
        "finance_decision": r["finance_decision"],
        "rejection_reason": r.get("rejection_reason"),
        "rework_count": r.get("rework_count", 0),
        "compliance_findings": list(r.get("compliance_findings") or []),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def create_reimbursement(actor_id, body):
    project_id = require_field(body, "project_id", str)
    project = db.projects.get(project_id)
    if project is None:
        raise_error(ERR_PROJECT_NOT_FOUND, f"project {project_id} not found")
    if project["principal_investigator_id"] != actor_id:
        raise_error(ERR_NOT_PROJECT_OWNER, "only PI can create reimbursement")

    bi_id = require_field(body, "budget_item_id", str)
    bi = db.budget_items.get(bi_id)
    if bi is None:
        raise_error(ERR_BUDGET_ITEM_NOT_FOUND, f"budget item {bi_id} not found")
    if bi["project_id"] != project_id:
        raise_error(ERR_BUDGET_ITEM_NOT_FOUND, "budget item does not belong to this project")

    expense_category = require_field(body, "expense_category", str)
    if expense_category not in VALID_CATEGORIES:
        raise_error(ERR_INVALID_INPUT, "invalid expense_category")

    amount = round_money(to_decimal(require_field(body, "amount")))
    if amount <= 0:
        raise_error(ERR_INVALID_INPUT, "amount must be > 0")
    invoice_number = require_field(body, "invoice_number", str)
    invoice_date = require_field(body, "invoice_date", int)
    invoice_authenticated = require_field(body, "invoice_authenticated", bool)
    attachments_raw = require_field(body, "attachments", list)
    attachments = []
    for att in attachments_raw:
        if not isinstance(att, dict):
            raise_error(ERR_INVALID_INPUT, "attachment entries must be objects")
        filename = att.get("filename")
        kind = att.get("kind")
        if not isinstance(filename, str) or not isinstance(kind, str):
            raise_error(ERR_INVALID_INPUT, "attachment requires filename and kind strings")
        attachments.append({"filename": filename, "kind": kind})
    vendor_id = require_field(body, "vendor_id", str)

    # Category match check (creation-time)
    if expense_category != bi["category"]:
        raise_error(ERR_CATEGORY_MISMATCH, "expense_category != budget item category")

    # Invoice date range check
    now = clock.now_epoch()
    if invoice_date < project["planned_start_date"] or invoice_date > now:
        raise_error(ERR_INVOICE_DATE_OUT_OF_RANGE, "invoice_date outside [planned_start_date, now()]")

    # Duplicate invoice number check (case-insensitive within project)
    inv_lower = invoice_number.lower()
    for existing in db.reimbursements.values():
        if existing["project_id"] == project_id and existing["invoice_number"].lower() == inv_lower:
            raise_error(ERR_DUPLICATE_INVOICE_NUMBER, "invoice_number already used on this project")

    rid = db.new_id()
    rec = {
        "id": rid,
        "project_id": project_id,
        "budget_item_id": bi_id,
        "expense_category": expense_category,
        "amount": amount,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "invoice_authenticated": invoice_authenticated,
        "attachments": attachments,
        "vendor_id": vendor_id,
        "pi_decision": "PENDING",
        "dept_decision": "PENDING",
        "finance_decision": "PENDING",
        "rejection_reason": None,
        "rework_count": 0,
        "compliance_findings": [],
        "status": "DRAFT",
    }
    stamp_create(rec)
    db.reimbursements[rid] = rec
    append_log("REIMBURSEMENT", rid, "CREATE", "PrincipalInvestigator", actor_id,
               {}, {"status": "DRAFT", "amount": money_to_json(amount)})
    return rec


def list_reimbursements(project_id=None, status=None):
    items = list(db.reimbursements.values())
    if project_id:
        items = [r for r in items if r["project_id"] == project_id]
    if status:
        items = [r for r in items if r["status"] == status]
    return sort_by_created_at(items)


def _run_compliance_prescreen(reimbursement, project):
    """Run compliance pre-screen. Returns (findings, has_block)."""
    findings = []
    funding_source = project["funding_source"]
    category = reimbursement["expense_category"]

    # Conflict-of-interest check (BLOCK, all categories)
    if (reimbursement["vendor_id"] == project["principal_investigator_id"] or
            reimbursement["vendor_id"] == project["department_id"]):
        findings.append({"rule_id": "COI", "severity": "BLOCK"})

    # Per-diem (TRAVEL, ESCALATE on strictly greater than)
    if category == "TRAVEL":
        rules = find_active_rules("PER_DIEM_CAP", funding_source, category)
        for rule in rules:
            cap = rule.get("parameters", {}).get("daily_cap")
            if cap is not None:
                cap_dec = to_decimal(cap)
                if reimbursement["amount"] > cap_dec:
                    severity = rule.get("severity", "ESCALATE")
                    findings.append({"rule_id": "PER_DIEM_CAP", "severity": severity})
                    break

    # Equipment threshold (EQUIPMENT, ESCALATE on >= threshold)
    if category == "EQUIPMENT":
        rules = find_active_rules("EQUIP_THRESHOLD", funding_source, category)
        for rule in rules:
            threshold = rule.get("parameters", {}).get("threshold_amount")
            if threshold is not None:
                threshold_dec = to_decimal(threshold)
                if reimbursement["amount"] >= threshold_dec:
                    severity = rule.get("severity", "ESCALATE")
                    findings.append({"rule_id": "EQUIP_THRESHOLD", "severity": severity})
                    break

    has_block = any(f["severity"] == "BLOCK" for f in findings)
    return findings, has_block


def submit_reimbursement(reimbursement_id, actor_id):
    r = get_reimbursement_or_404(reimbursement_id)
    project = db.projects.get(r["project_id"])
    if project is None:
        raise_error(ERR_PROJECT_NOT_FOUND, "project missing")
    if project["principal_investigator_id"] != actor_id:
        raise_error(ERR_NOT_PROJECT_OWNER, "only PI can submit")
    if r["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, f"reimbursement not DRAFT (got {r['status']})")
    if project["status"] != "ACTIVE":
        raise_error(ERR_PROJECT_NOT_ACTIVE, "project not ACTIVE")

    bi = db.budget_items.get(r["budget_item_id"])
    if bi is None:
        raise_error(ERR_BUDGET_ITEM_NOT_FOUND, "budget item missing")
    if bi["status"] != "APPROVED":
        raise_error(ERR_BUDGET_NOT_APPROVED, "budget item not APPROVED")

    # Priority order per PRD §2.7:
    # business_safety (invoice_authentic, attachments, compliance_block) BEFORE business_referential (category)
    if not r["invoice_authenticated"]:
        raise_error(ERR_INVOICE_NOT_AUTHENTIC, "invoice not authenticated")

    has_invoice = any(att.get("kind") == "INVOICE" for att in r["attachments"])
    has_receipt = any(att.get("kind") == "RECEIPT" for att in r["attachments"])
    if not (has_invoice and has_receipt):
        raise_error(ERR_ATTACHMENTS_INCOMPLETE, "attachments must include INVOICE and RECEIPT")

    # Compliance pre-screen — BLOCK rejects outright
    findings, has_block = _run_compliance_prescreen(r, project)
    if has_block:
        raise_error(ERR_COMPLIANCE_BLOCK, "compliance pre-screen produced BLOCK finding")

    # Category match check (re-run at submit)
    if r["expense_category"] != bi["category"]:
        raise_error(ERR_CATEGORY_MISMATCH, "expense_category != budget item category")

    # Rework limit
    if r["rework_count"] > 3:
        raise_error(ERR_REWORK_LIMIT_EXCEEDED, "rework_count > 3")

    r["compliance_findings"] = findings
    r["rejection_reason"] = None
    r["status"] = "SUBMITTED"
    stamp_update(r)
    append_log("REIMBURSEMENT", r["id"], "UPDATE", "PrincipalInvestigator", actor_id,
               {"status": "DRAFT"}, {"status": "SUBMITTED"})
    return r


def pi_approve_reimbursement(reimbursement_id, actor_id):
    r = get_reimbursement_or_404(reimbursement_id)
    project = db.projects.get(r["project_id"])
    if project is None:
        raise_error(ERR_PROJECT_NOT_FOUND, "project missing")
    if project["principal_investigator_id"] != actor_id:
        raise_error(ERR_NOT_PROJECT_OWNER, "only PI can approve")
    if r["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, f"reimbursement not SUBMITTED (got {r['status']})")
    # ESCALATE finding without override blocks PI approval
    has_unresolved_escalate = any(
        f.get("severity") == "ESCALATE" and not f.get("override_resolved", False)
        for f in (r.get("compliance_findings") or [])
    )
    if has_unresolved_escalate:
        raise_error(ERR_ESCALATION_PENDING, "unresolved ESCALATE compliance finding")
    r["pi_decision"] = "APPROVED"
    r["status"] = "UNDER_REVIEW"
    stamp_update(r)
    append_log("REIMBURSEMENT", r["id"], "APPROVE", "PrincipalInvestigator", actor_id,
               {"status": "SUBMITTED"}, {"status": "UNDER_REVIEW", "pi_decision": "APPROVED"})
    return r


def dept_approve_reimbursement(reimbursement_id, actor_id):
    r = get_reimbursement_or_404(reimbursement_id)
    if r["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, f"reimbursement not UNDER_REVIEW (got {r['status']})")
    if r["pi_decision"] != "APPROVED":
        raise_error(ERR_PI_DECISION_PENDING, "pi decision pending")
    r["dept_decision"] = "APPROVED"
    stamp_update(r)
    append_log("REIMBURSEMENT", r["id"], "APPROVE", "DepartmentApprover", actor_id,
               {"dept_decision": "PENDING"}, {"dept_decision": "APPROVED"})
    return r


def finance_approve_reimbursement(reimbursement_id, actor_id):
    r = get_reimbursement_or_404(reimbursement_id)
    if r["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, f"reimbursement not UNDER_REVIEW (got {r['status']})")
    if r["dept_decision"] != "APPROVED":
        raise_error(ERR_DEPT_DECISION_PENDING, "department decision pending")
    bi = db.budget_items.get(r["budget_item_id"])
    if bi is None:
        raise_error(ERR_BUDGET_ITEM_NOT_FOUND, "budget item missing")
    remaining = bi.get("remaining_amount")
    if remaining is None:
        approved = bi.get("approved_amount") or Decimal("0.00")
        spent = bi.get("spent_amount") or Decimal("0.00")
        remaining = approved - spent
    if remaining < r["amount"]:
        raise_error(ERR_BUDGET_INSUFFICIENT, "remaining_amount < reimbursement.amount")
    r["finance_decision"] = "APPROVED"
    r["status"] = "APPROVED"
    stamp_update(r)
    append_log("REIMBURSEMENT", r["id"], "APPROVE", "FinanceOfficer", actor_id,
               {"status": "UNDER_REVIEW"}, {"status": "APPROVED"})
    return r


def mark_paid(reimbursement_id, actor_id):
    r = get_reimbursement_or_404(reimbursement_id)
    if r["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE, f"reimbursement not APPROVED (got {r['status']})")
    bi = db.budget_items.get(r["budget_item_id"])
    if bi is None:
        raise_error(ERR_BUDGET_ITEM_NOT_FOUND, "budget item missing")
    project = db.projects.get(r["project_id"])
    if project is None:
        raise_error(ERR_PROJECT_NOT_FOUND, "project missing")

    bi_before = {
        "spent_amount": money_to_json(bi.get("spent_amount") or Decimal("0.00")),
        "remaining_amount": money_to_json(bi.get("remaining_amount") or Decimal("0.00")),
        "version": bi["version"],
    }
    bi["spent_amount"] = round_money((bi.get("spent_amount") or Decimal("0.00")) + r["amount"])
    approved = bi.get("approved_amount") or Decimal("0.00")
    bi["remaining_amount"] = round_money(approved - bi["spent_amount"])
    stamp_update(bi)
    bi_after = {
        "spent_amount": money_to_json(bi["spent_amount"]),
        "remaining_amount": money_to_json(bi["remaining_amount"]),
        "version": bi["version"],
    }

    project["total_reimbursed"] = round_money((project.get("total_reimbursed") or Decimal("0.00")) + r["amount"])
    stamp_update(project)

    r["status"] = "PAID"
    stamp_update(r)
    append_log("REIMBURSEMENT", r["id"], "PAY", "FinanceOfficer", actor_id,
               {"status": "APPROVED"}, {"status": "PAID"})
    append_log("BUDGET_ITEM", bi["id"], "UPDATE", "FinanceOfficer", actor_id, bi_before, bi_after)
    return r


def reject_reimbursement(reimbursement_id, actor_id, actor_role, body):
    r = get_reimbursement_or_404(reimbursement_id)
    if r["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, f"reimbursement not UNDER_REVIEW (got {r['status']})")
    rejection_reason = (body or {}).get("rejection_reason", "")

    # Decide between rework loop or terminal rejection.
    # Per PRD §3.3: rework_count must be < 3 to issue a normal reject (back to DRAFT, increment rework_count).
    # When rework_count == 3 and a further reject is attempted, automatic terminal transition to REJECTED.
    if r["rework_count"] >= 3:
        # automatic terminal transition
        if not isinstance(rejection_reason, str) or not rejection_reason.strip():
            raise_error(ERR_REJECTION_REASON_REQUIRED, "rejection_reason required")
        if actor_role == "DepartmentApprover":
            r["dept_decision"] = "REJECTED"
        elif actor_role == "FinanceOfficer":
            r["finance_decision"] = "REJECTED"
        r["rejection_reason"] = rejection_reason
        r["status"] = "REJECTED"
        stamp_update(r)
        append_log("REIMBURSEMENT", r["id"], "REJECT", actor_role, actor_id,
                   {"status": "UNDER_REVIEW"}, {"status": "REJECTED"})
        return r

    # Normal reject path: rework_count < 3, requires non-empty rejection_reason
    if not isinstance(rejection_reason, str) or not rejection_reason.strip():
        raise_error(ERR_REJECTION_REASON_REQUIRED, "rejection_reason required")
    if actor_role == "DepartmentApprover":
        r["dept_decision"] = "REJECTED"
    elif actor_role == "FinanceOfficer":
        r["finance_decision"] = "REJECTED"
    r["rejection_reason"] = rejection_reason
    r["rework_count"] += 1
    r["status"] = "DRAFT"
    stamp_update(r)
    append_log("REIMBURSEMENT", r["id"], "REJECT", actor_role, actor_id,
               {"status": "UNDER_REVIEW"}, {"status": "DRAFT", "rework_count": r["rework_count"]})
    return r


def rework_reimbursement(reimbursement_id, actor_id):
    r = get_reimbursement_or_404(reimbursement_id)
    project = db.projects.get(r["project_id"])
    if project is None:
        raise_error(ERR_PROJECT_NOT_FOUND, "project missing")
    if project["principal_investigator_id"] != actor_id:
        raise_error(ERR_NOT_PROJECT_OWNER, "only PI can rework")
    if r["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, f"reimbursement not SUBMITTED (got {r['status']})")
    if r["rework_count"] >= 3:
        raise_error(ERR_REWORK_LIMIT_EXCEEDED, "rework_count >= 3")
    r["rework_count"] += 1
    r["status"] = "DRAFT"
    r["pi_decision"] = "PENDING"
    r["dept_decision"] = "PENDING"
    r["finance_decision"] = "PENDING"
    stamp_update(r)
    append_log("REIMBURSEMENT", r["id"], "REWORK", "PrincipalInvestigator", actor_id,
               {"status": "SUBMITTED"}, {"status": "DRAFT", "rework_count": r["rework_count"]})
    return r
