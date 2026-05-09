"""ClosingAudit — submit/flag/resubmit/close, with execution rate computation."""

from decimal import Decimal

from common import (
    rate_to_json,
    require_field,
    round_rate,
    sort_by_created_at,
    stamp_create,
    stamp_update,
)
from db import db
from errors import (
    ERR_CLOSING_AUDIT_NOT_FOUND,
    ERR_DELIVERABLES_INCOMPLETE,
    ERR_FINDINGS_NOT_RECTIFIED,
    ERR_HIGH_FINDINGS_NOT_RECTIFIED,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_NO_HIGH_FINDINGS,
    ERR_NOT_PROJECT_OWNER,
    ERR_PROJECT_NOT_CLOSING,
    ERR_PROJECT_NOT_FOUND,
    ERR_RESIDUAL_ACTION_NOT_ALLOWED,
    raise_error,
)
from services.indirect_cost import run_allocation


VALID_RESIDUAL = {"RETURN", "REALLOCATE", "CARRYOVER"}
VALID_SEVERITY = {"LOW", "MEDIUM", "HIGH"}


def get_audit_or_404(audit_id):
    a = db.closing_audits.get(audit_id)
    if a is None:
        raise_error(ERR_CLOSING_AUDIT_NOT_FOUND, f"closing audit {audit_id} not found")
    return a


def serialize_audit(a):
    return {
        "id": a["id"],
        "project_id": a["project_id"],
        "deliverables": list(a.get("deliverables") or []),
        "residual_fund_action": a["residual_fund_action"],
        "audit_findings": list(a.get("audit_findings") or []),
        "budget_execution_rate": rate_to_json(a["budget_execution_rate"]) if a.get("budget_execution_rate") is not None else None,
        "forward_execution_rate": rate_to_json(a["forward_execution_rate"]) if a.get("forward_execution_rate") is not None else None,
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def create_audit(actor_id, body):
    project_id = require_field(body, "project_id", str)
    project = db.projects.get(project_id)
    if project is None:
        raise_error(ERR_PROJECT_NOT_FOUND, f"project {project_id} not found")
    if project["principal_investigator_id"] != actor_id:
        raise_error(ERR_NOT_PROJECT_OWNER, "only PI can create audit")
    # One audit per project
    for existing in db.closing_audits.values():
        if existing["project_id"] == project_id:
            raise_error(ERR_INVALID_STATE, "closing audit already exists for project")

    deliverables_raw = require_field(body, "deliverables", list)
    deliverables = []
    for d in deliverables_raw:
        if not isinstance(d, dict):
            raise_error(ERR_INVALID_INPUT, "deliverable must be object")
        title = d.get("title")
        kind = d.get("kind")
        url = d.get("url")
        if not all(isinstance(x, str) for x in (title, kind, url)):
            raise_error(ERR_INVALID_INPUT, "deliverable requires title/kind/url strings")
        deliverables.append({"title": title, "kind": kind, "url": url})

    residual_fund_action = require_field(body, "residual_fund_action", str)
    if residual_fund_action not in VALID_RESIDUAL:
        raise_error(ERR_INVALID_INPUT, "invalid residual_fund_action")

    audit_findings_raw = require_field(body, "audit_findings", list)
    audit_findings = []
    for f in audit_findings_raw:
        if not isinstance(f, dict):
            raise_error(ERR_INVALID_INPUT, "audit_finding must be object")
        finding_id = f.get("finding_id")
        severity = f.get("severity")
        description = f.get("description")
        rectified = f.get("rectified", False)
        if not isinstance(finding_id, str) or severity not in VALID_SEVERITY or not isinstance(description, str):
            raise_error(ERR_INVALID_INPUT, "audit_finding requires finding_id, severity, description")
        if not isinstance(rectified, bool):
            raise_error(ERR_INVALID_INPUT, "rectified must be boolean")
        audit_findings.append({
            "finding_id": finding_id, "severity": severity,
            "description": description, "rectified": rectified,
        })

    aid = db.new_id()
    audit = {
        "id": aid,
        "project_id": project_id,
        "deliverables": deliverables,
        "residual_fund_action": residual_fund_action,
        "audit_findings": audit_findings,
        "budget_execution_rate": None,
        "forward_execution_rate": None,
        "status": "DRAFT",
    }
    stamp_create(audit)
    db.closing_audits[aid] = audit
    return audit


def _compute_execution_rates(project_id):
    """Returns (budget_execution_rate, forward_execution_rate) as Decimal."""
    paid_total = Decimal("0.00")
    fwd_extra = Decimal("0.00")
    for r in db.reimbursements.values():
        if r["project_id"] != project_id:
            continue
        if r["status"] == "PAID":
            paid_total += r["amount"]
        elif r["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED"):
            fwd_extra += r["amount"]

    denom = Decimal("0.00")
    for bi in db.budget_items.values():
        if bi["project_id"] == project_id and bi.get("approved_amount") is not None:
            denom += bi["approved_amount"]

    if denom == 0:
        return Decimal("0.0000"), Decimal("0.0000")
    chrono = round_rate(paid_total / denom)
    forward = round_rate((paid_total + fwd_extra) / denom)
    return chrono, forward


def _residual_allowed(funding_source, action, exec_rate):
    table = {
        "NATIONAL":   {"RETURN": True,  "REALLOCATE": False, "CARRYOVER": exec_rate >= Decimal("0.95")},
        "PROVINCIAL": {"RETURN": True,  "REALLOCATE": False, "CARRYOVER": exec_rate >= Decimal("0.90")},
        "ENTERPRISE": {"RETURN": False, "REALLOCATE": True,  "CARRYOVER": True},
        "INTERNAL":   {"RETURN": True,  "REALLOCATE": True,  "CARRYOVER": True},
    }
    return table[funding_source][action]


def submit_audit(audit_id, actor_id):
    a = get_audit_or_404(audit_id)
    project = db.projects.get(a["project_id"])
    if project is None:
        raise_error(ERR_PROJECT_NOT_FOUND, "project missing")
    if project["principal_investigator_id"] != actor_id:
        raise_error(ERR_NOT_PROJECT_OWNER, "only PI can submit audit")
    if a["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, f"audit not DRAFT (got {a['status']})")
    if project["status"] != "CLOSING":
        raise_error(ERR_PROJECT_NOT_CLOSING, "project not CLOSING")
    has_report = any(d.get("kind") == "REPORT" for d in a["deliverables"])
    has_dataset = any(d.get("kind") == "DATASET" for d in a["deliverables"])
    if not (has_report and has_dataset):
        raise_error(ERR_DELIVERABLES_INCOMPLETE, "deliverables must include REPORT and DATASET")

    chrono, forward = _compute_execution_rates(a["project_id"])
    if not _residual_allowed(project["funding_source"], a["residual_fund_action"], chrono):
        raise_error(ERR_RESIDUAL_ACTION_NOT_ALLOWED, "residual_fund_action not permitted")

    a["budget_execution_rate"] = chrono
    a["forward_execution_rate"] = forward
    a["status"] = "SUBMITTED"
    stamp_update(a)

    # Update project's closing_findings_count to reflect this audit
    project["closing_findings_count"] = len(a.get("audit_findings") or [])
    stamp_update(project)
    return a


def flag_rectification(audit_id):
    a = get_audit_or_404(audit_id)
    if a["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, f"audit not SUBMITTED (got {a['status']})")
    has_high = any(f.get("severity") == "HIGH" for f in a["audit_findings"])
    if not has_high:
        raise_error(ERR_NO_HIGH_FINDINGS, "no HIGH-severity findings present")
    a["status"] = "RECTIFICATION_REQUIRED"
    stamp_update(a)
    return a


def resubmit_audit(audit_id, actor_id, body):
    a = get_audit_or_404(audit_id)
    project = db.projects.get(a["project_id"])
    if project is None:
        raise_error(ERR_PROJECT_NOT_FOUND, "project missing")
    if project["principal_investigator_id"] != actor_id:
        raise_error(ERR_NOT_PROJECT_OWNER, "only PI can resubmit audit")
    if a["status"] != "RECTIFICATION_REQUIRED":
        raise_error(ERR_INVALID_STATE, f"audit not RECTIFICATION_REQUIRED (got {a['status']})")

    # Allow body to update audit_findings to mark items rectified=true (optional).
    if body and "audit_findings" in body:
        af_raw = body["audit_findings"]
        if not isinstance(af_raw, list):
            raise_error(ERR_INVALID_INPUT, "audit_findings must be list")
        new_findings = []
        for f in af_raw:
            if not isinstance(f, dict):
                raise_error(ERR_INVALID_INPUT, "audit_finding must be object")
            new_findings.append({
                "finding_id": f.get("finding_id"),
                "severity": f.get("severity"),
                "description": f.get("description"),
                "rectified": bool(f.get("rectified", False)),
            })
        a["audit_findings"] = new_findings

    for f in a["audit_findings"]:
        if f.get("severity") == "HIGH" and not f.get("rectified", False):
            raise_error(ERR_HIGH_FINDINGS_NOT_RECTIFIED, "all HIGH findings must be rectified")

    a["status"] = "SUBMITTED"
    # Refresh execution rates since project state may have changed
    chrono, forward = _compute_execution_rates(a["project_id"])
    a["budget_execution_rate"] = chrono
    a["forward_execution_rate"] = forward
    stamp_update(a)
    return a


def close_audit(audit_id):
    a = get_audit_or_404(audit_id)
    project = db.projects.get(a["project_id"])
    if project is None:
        raise_error(ERR_PROJECT_NOT_FOUND, "project missing")
    if a["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, f"audit not SUBMITTED (got {a['status']})")
    for f in a["audit_findings"]:
        if f.get("severity") in ("MEDIUM", "HIGH") and not f.get("rectified", False):
            raise_error(ERR_FINDINGS_NOT_RECTIFIED, "all MEDIUM/HIGH findings must be rectified")
    a["status"] = "CLOSED"
    stamp_update(a)

    # Cascade: project -> CLOSED
    project["status"] = "CLOSED"
    stamp_update(project)

    # Cascade: run a final IndirectCostAllocation for the project
    run_id, allocations = run_allocation("DIRECT_COST", project_id=project["id"])
    if allocations:
        project["indirect_cost_amount"] = allocations[0]["allocated_amount"]
        stamp_update(project)
    return a


def list_audits(project_id=None):
    items = list(db.closing_audits.values())
    if project_id:
        items = [a for a in items if a["project_id"] == project_id]
    return sort_by_created_at(items)
