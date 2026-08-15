"""AuditEngagement endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import store, base_resource, touch, parse_iso
from errors import (
    err, ERR_PRODUCT_NOT_FOUND, ERR_AUDIT_ENGAGEMENT_NOT_FOUND,
    ERR_ENGAGEMENT_NOT_INITIATED, ERR_ENGAGEMENT_NOT_SCOPING,
    ERR_ENGAGEMENT_NOT_DATA_COLLECTION, ERR_ENGAGEMENT_NOT_ANALYSIS,
    ERR_ENGAGEMENT_NOT_REPORT_DRAFT, ERR_ENGAGEMENT_NOT_CANCELLABLE,
    ERR_INVALID_REQUEST,
)
from middleware import require_roles, get_auth, get_json_body
from response import success_obj, success_list, parse_pagination
from services import engine
from services.engine import sha256_hex

bp = Blueprint("engagements", __name__)

AUDIT_TYPES = {"M_AND_A", "IPO_READINESS", "CUSTOMER_DUE_DILIGENCE", "REGULATORY_INQUIRY"}


def engagement_view(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def _resolve(productId, engagementId=None):
    p = store.products.get(productId)
    if not p:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    e = None
    if engagementId is not None:
        e = store.engagements.get(engagementId)
        if not e or e["product_id"] != productId:
            raise err(ERR_AUDIT_ENGAGEMENT_NOT_FOUND, "AuditEngagement not found")
    return p, e


@bp.route("/oss-products/<productId>/audit-engagements", methods=["POST"])
def create_engagement(productId):
    require_roles("ComplianceAnalyst")
    p = store.products.get(productId)
    if not p:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    body = get_json_body()
    audit_type = body.get("audit_type")
    if audit_type not in AUDIT_TYPES:
        raise err(ERR_INVALID_REQUEST,
                  "audit_type must be M_AND_A, IPO_READINESS, CUSTOMER_DUE_DILIGENCE, or REGULATORY_INQUIRY")
    requesting_party = body.get("requesting_party")
    scope_description = body.get("scope_description")
    target_completion_at = body.get("target_completion_at")
    if not requesting_party:
        raise err(ERR_INVALID_REQUEST, "requesting_party is required")
    if not scope_description:
        raise err(ERR_INVALID_REQUEST, "scope_description is required")
    if not target_completion_at:
        raise err(ERR_INVALID_REQUEST, "target_completion_at is required")

    e = base_resource()
    e.update({
        "product_id": productId,
        "audit_type": audit_type,
        "requesting_party": requesting_party,
        "scope_description": scope_description,
        "status": "INITIATED",
        "target_completion_at": target_completion_at,
        "actual_completion_at": None,
        "findings_summary": None,
        "critical_findings_count": 0,
        "report_hash": None,
        "_snapshot_bom_ids": [],
        "_snapshot_finding_ids": [],
    })
    store.engagements[e["id"]] = e
    return success_obj(engagement_view(e), status=201)


@bp.route("/oss-products/<productId>/audit-engagements", methods=["GET"])
def list_engagements(productId):
    get_auth()
    _resolve(productId)
    limit, offset = parse_pagination(request.args)
    items = [e for e in store.engagements.values() if e["product_id"] == productId]
    status = request.args.get("status")
    if status:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([engagement_view(e) for e in page], limit, offset, total)


@bp.route("/oss-products/<productId>/audit-engagements/<engagementId>", methods=["GET"])
def get_engagement(productId, engagementId):
    get_auth()
    _, e = _resolve(productId, engagementId)
    return success_obj(engagement_view(e))


@bp.route("/oss-products/<productId>/audit-engagements/<engagementId>/start-scoping", methods=["POST"])
def start_scoping(productId, engagementId):
    require_roles("ComplianceAnalyst")
    _, e = _resolve(productId, engagementId)
    if e["status"] != "INITIATED":
        raise err(ERR_ENGAGEMENT_NOT_INITIATED, "AuditEngagement must be INITIATED")
    e["status"] = "SCOPING"
    touch(e)
    return success_obj(engagement_view(e))


@bp.route("/oss-products/<productId>/audit-engagements/<engagementId>/start-data-collection", methods=["POST"])
def start_data_collection(productId, engagementId):
    require_roles("ComplianceAnalyst")
    _, e = _resolve(productId, engagementId)
    if e["status"] != "SCOPING":
        raise err(ERR_ENGAGEMENT_NOT_SCOPING, "AuditEngagement must be SCOPING")
    e["status"] = "DATA_COLLECTION"
    # Snapshot of all FINALIZED BOMs + all open VulnerabilityFindings
    e["_snapshot_bom_ids"] = [b["id"] for b in store.boms.values()
                              if b["product_id"] == productId and b["status"] == "FINALIZED"]
    e["_snapshot_finding_ids"] = [f["id"] for f in store.findings.values()
                                  if f["product_id"] == productId and f["status"] in ("OPEN", "CONFIRMED", "MITIGATED")]
    touch(e)
    return success_obj(engagement_view(e))


@bp.route("/oss-products/<productId>/audit-engagements/<engagementId>/start-analysis", methods=["POST"])
def start_analysis(productId, engagementId):
    require_roles("ComplianceAnalyst")
    _, e = _resolve(productId, engagementId)
    if e["status"] != "DATA_COLLECTION":
        raise err(ERR_ENGAGEMENT_NOT_DATA_COLLECTION, "AuditEngagement must be DATA_COLLECTION")
    e["status"] = "ANALYSIS"
    touch(e)
    return success_obj(engagement_view(e))


@bp.route("/oss-products/<productId>/audit-engagements/<engagementId>/draft-report", methods=["POST"])
def draft_report(productId, engagementId):
    require_roles("ComplianceAnalyst")
    p, e = _resolve(productId, engagementId)
    if e["status"] != "ANALYSIS":
        raise err(ERR_ENGAGEMENT_NOT_ANALYSIS, "AuditEngagement must be ANALYSIS")
    e["status"] = "REPORT_DRAFT"

    # critical_findings_count aggregation
    now = store.now()
    critical = 0
    from services.policy import effective_classification
    for b in store.boms.values():
        if b["product_id"] != productId or b["status"] != "FINALIZED":
            continue
        for entry in engine.entries_of_bom(b["id"]):
            comp = store.components.get(entry["component_id"])
            eff = effective_classification(comp) if comp else None
            if eff == "PROHIBITED":
                critical += 1
            elif eff == "RESTRICTED":
                # expired or missing approvals
                appr = [a for a in store.approvals.values()
                        if a["bom_entry_id"] == entry["id"] and a["status"] == "APPROVED"]
                ok = False
                for a in appr:
                    exp = a.get("expiry_at")
                    if exp is None or parse_iso(exp) >= now:
                        ok = True
                        break
                if not ok:
                    critical += 1
    for f in store.findings.values():
        if f["product_id"] != productId or f["status"] not in ("OPEN", "CONFIRMED"):
            continue
        vuln = store.vulnerabilities.get(f["vulnerability_id"])
        if vuln and vuln["severity"] == "CRITICAL":
            critical += 1
    for t in store.tickets.values():
        if t["product_id"] != productId or t["status"] != "OVERDUE":
            continue
        due = t.get("due_at")
        if due and parse_iso(due) + timedelta(days=30) < now:
            critical += 1

    e["critical_findings_count"] = critical
    e["findings_summary"] = (
        f"Audit findings: {critical} critical finding(s) identified across "
        f"finalized BOMs, open vulnerabilities, restricted approvals, and overdue obligations."
    )
    touch(e)
    return success_obj(engagement_view(e))


@bp.route("/oss-products/<productId>/audit-engagements/<engagementId>/finalize-report", methods=["POST"])
def finalize_report(productId, engagementId):
    require_roles("LegalCounsel")
    _, e = _resolve(productId, engagementId)
    if e["status"] != "REPORT_DRAFT":
        raise err(ERR_ENGAGEMENT_NOT_REPORT_DRAFT, "AuditEngagement must be REPORT_DRAFT")
    e["status"] = "REPORT_FINAL"
    e["actual_completion_at"] = store.now_iso()
    e["report_hash"] = sha256_hex(
        f"REPORT:{e['id']}:{e.get('findings_summary')}:{e.get('critical_findings_count')}"
    )
    touch(e)
    return success_obj(engagement_view(e))


@bp.route("/oss-products/<productId>/audit-engagements/<engagementId>/cancel", methods=["POST"])
def cancel_engagement(productId, engagementId):
    require_roles("ComplianceAnalyst")
    _, e = _resolve(productId, engagementId)
    if e["status"] not in ("INITIATED", "SCOPING", "DATA_COLLECTION"):
        raise err(ERR_ENGAGEMENT_NOT_CANCELLABLE,
                  "AuditEngagement must be INITIATED, SCOPING, or DATA_COLLECTION")
    e["status"] = "CANCELLED"
    touch(e)
    return success_obj(engagement_view(e))
