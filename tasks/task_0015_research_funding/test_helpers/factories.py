"""Payload factories for the Research Funding API — input fields only, exact PRD field names.

PRD §3.1 (Project create), §3.2 (BudgetAdjustment), §3.3 (Reimbursement create),
§3.4 (ComplianceRule create), §3.5 (ClosingAudit create), §3.8 (allocation runs).
"""
from typing import Any, Dict, List, Optional
import uuid


# ---- Default proposal text (>= 200 chars per PRD §3.1) ----
def _default_proposal_text() -> str:
    base = (
        "This proposal investigates novel computational methods for analyzing "
        "research data with applications across multiple scientific domains. "
        "We will conduct experiments, gather measurements, build statistical "
        "models, and publish reproducible findings under open-access licenses. "
        "Outcomes include datasets, technical reports, and conference papers. "
    )
    # Pad to ensure >= 200 characters even if truncated.
    while len(base) < 220:
        base += " Additional context paragraph content for the proposal body. "
    return base


def create_project_payload(*,
                            principal_investigator_id: str,
                            funding_source: str = "NATIONAL",
                            planned_start_date: int,
                            planned_end_date: int,
                            **overrides) -> Dict[str, Any]:
    """Project create payload (PRD §3.1).

    All field names are PRD-exact:
      - title (1..200 chars)
      - principal_investigator_id (must equal X-User-ID at creation)
      - department_id
      - funding_source: NATIONAL | PROVINCIAL | ENTERPRISE | INTERNAL
      - proposal_text
      - requested_amount (CNY, two decimals)
      - planned_start_date / planned_end_date (Unix epoch seconds)
    """
    p: Dict[str, Any] = {
        "title": f"Test Project {uuid.uuid4().hex[:8]}",
        "principal_investigator_id": principal_investigator_id,
        "department_id": f"DEPT-{uuid.uuid4().hex[:6]}",
        "funding_source": funding_source,
        "proposal_text": _default_proposal_text(),
        "requested_amount": 100000.00,
        "planned_start_date": planned_start_date,
        "planned_end_date": planned_end_date,
    }
    p.update(overrides)
    return p


def create_budget_item_payload(*, category: str, requested_amount: float, **overrides) -> Dict[str, Any]:
    """BudgetItem create payload (PRD §3.1)."""
    p: Dict[str, Any] = {
        "category": category,
        "requested_amount": requested_amount,
    }
    p.update(overrides)
    return p


def create_peer_review_payload(*, reviewer_id: str, recommendation: str, score: int = 80,
                                comments: str = "Solid proposal.",
                                **overrides) -> Dict[str, Any]:
    """PeerReview create payload (PRD §3.1).

    - reviewer_id: opaque user id (the X-User-ID of the acting reviewer)
    - score: 0..100
    - recommendation: APPROVE | REJECT | REVISE
    - comments: free text
    """
    p: Dict[str, Any] = {
        "reviewer_id": reviewer_id,
        "score": score,
        "recommendation": recommendation,
        "comments": comments,
    }
    p.update(overrides)
    return p


def create_budget_adjustment_payload(*, project_id: str,
                                      line_changes: List[Dict[str, Any]],
                                      justification: str = "Reallocating funds between budget categories for unforeseen experimental needs.",
                                      **overrides) -> Dict[str, Any]:
    """BudgetAdjustment create payload (PRD §3.2).

    - project_id (FK)
    - line_changes: array of {budget_item_id, delta_amount}; must sum to 0 within 0.01
    - justification: >= 20 chars
    """
    p: Dict[str, Any] = {
        "project_id": project_id,
        "line_changes": line_changes,
        "justification": justification,
    }
    p.update(overrides)
    return p


def create_reimbursement_payload(*, project_id: str, budget_item_id: str,
                                  expense_category: str, amount: float,
                                  invoice_date: int,
                                  invoice_number: Optional[str] = None,
                                  invoice_authenticated: bool = True,
                                  attachments: Optional[List[Dict[str, str]]] = None,
                                  vendor_id: Optional[str] = None,
                                  **overrides) -> Dict[str, Any]:
    """Reimbursement create payload (PRD §3.3).

    - project_id (FK)
    - budget_item_id (FK; expense_category must equal BudgetItem.category)
    - expense_category: same enum as BudgetItem.category
    - amount: CNY > 0, two decimals
    - invoice_number: unique per project (case-insensitive)
    - invoice_date: Unix epoch seconds in [planned_start_date, now()]
    - invoice_authenticated: client-supplied authenticity flag (must be true at submit)
    - attachments: at least kind=INVOICE and kind=RECEIPT must be present at submit
    - vendor_id: vendor identifier (CoI: must not equal PI or department)
    """
    if invoice_number is None:
        invoice_number = f"INV-{uuid.uuid4().hex[:10].upper()}"
    if attachments is None:
        attachments = [
            {"filename": "invoice.pdf", "kind": "INVOICE"},
            {"filename": "receipt.pdf", "kind": "RECEIPT"},
        ]
    if vendor_id is None:
        vendor_id = f"VENDOR-{uuid.uuid4().hex[:8]}"
    p: Dict[str, Any] = {
        "project_id": project_id,
        "budget_item_id": budget_item_id,
        "expense_category": expense_category,
        "amount": amount,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "invoice_authenticated": invoice_authenticated,
        "attachments": attachments,
        "vendor_id": vendor_id,
    }
    p.update(overrides)
    return p


def create_compliance_rule_payload(*, rule_code: str,
                                    applies_to_funding_source: str = "ALL",
                                    applies_to_category: str = "ALL",
                                    parameters: Optional[Dict[str, Any]] = None,
                                    severity: str = "WARN",
                                    active: bool = True,
                                    **overrides) -> Dict[str, Any]:
    """ComplianceRule create payload (PRD §3.4)."""
    if parameters is None:
        parameters = {}
    p: Dict[str, Any] = {
        "rule_code": rule_code,
        "applies_to_funding_source": applies_to_funding_source,
        "applies_to_category": applies_to_category,
        "parameters": parameters,
        "severity": severity,
        "active": active,
    }
    p.update(overrides)
    return p


def patch_compliance_rule_payload(*, version: int,
                                   active: Optional[bool] = None,
                                   severity: Optional[str] = None,
                                   parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    p: Dict[str, Any] = {"version": version}
    if active is not None:
        p["active"] = active
    if severity is not None:
        p["severity"] = severity
    if parameters is not None:
        p["parameters"] = parameters
    return p


def create_closing_audit_payload(*, project_id: str,
                                  deliverables: Optional[List[Dict[str, str]]] = None,
                                  residual_fund_action: str = "RETURN",
                                  audit_findings: Optional[List[Dict[str, Any]]] = None,
                                  **overrides) -> Dict[str, Any]:
    """ClosingAudit create payload (PRD §3.5).

    - deliverables: array of {title, kind, url}; kinds REPORT and DATASET both required at submit
    - residual_fund_action: RETURN | REALLOCATE | CARRYOVER (subject to §3.7 policy)
    - audit_findings: array of {finding_id, severity, description, rectified}
    """
    if deliverables is None:
        deliverables = [
            {"title": "Final Report", "kind": "REPORT", "url": "https://example.com/report.pdf"},
            {"title": "Dataset", "kind": "DATASET", "url": "https://example.com/dataset.zip"},
        ]
    if audit_findings is None:
        audit_findings = []
    p: Dict[str, Any] = {
        "project_id": project_id,
        "deliverables": deliverables,
        "residual_fund_action": residual_fund_action,
        "audit_findings": audit_findings,
    }
    p.update(overrides)
    return p


def create_allocation_run_payload(*, allocation_base: str = "DIRECT_COST",
                                   project_id: Optional[str] = None,
                                   **overrides) -> Dict[str, Any]:
    """Allocation run payload (PRD §3.8). project_id is optional — when omitted, runs across
    every ACTIVE/CLOSING project."""
    p: Dict[str, Any] = {"allocation_base": allocation_base}
    if project_id is not None:
        p["project_id"] = project_id
    p.update(overrides)
    return p


def reject_payload(rejection_reason: str = "Insufficient documentation provided.") -> Dict[str, Any]:
    """Common reject body — used by both budget-adjustment and reimbursement reject endpoints."""
    return {"rejection_reason": rejection_reason}


def line_change(budget_item_id: str, delta_amount: float) -> Dict[str, Any]:
    """One element for BudgetAdjustment.line_changes."""
    return {"budget_item_id": budget_item_id, "delta_amount": delta_amount}


def attachment(filename: str, kind: str) -> Dict[str, str]:
    """One element for Reimbursement.attachments."""
    return {"filename": filename, "kind": kind}


def deliverable(title: str, kind: str, url: str = "https://example.com/deliverable") -> Dict[str, str]:
    """One element for ClosingAudit.deliverables."""
    return {"title": title, "kind": kind, "url": url}


def audit_finding(finding_id: str, severity: str, description: str = "Issue noted.",
                   rectified: bool = False) -> Dict[str, Any]:
    """One element for ClosingAudit.audit_findings."""
    return {
        "finding_id": finding_id,
        "severity": severity,
        "description": description,
        "rectified": rectified,
    }
