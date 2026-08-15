"""Standalone single-resource GET endpoints + flat filtered-list endpoints.

These live under the /oss-products prefix per the scaffold (FK reverse-reachability).
"""

from flask import Blueprint, request

from db import store
from errors import (
    err, ERR_PRODUCT_NOT_FOUND, ERR_COMPONENT_NOT_FOUND, ERR_SCAN_NOT_FOUND,
    ERR_BOM_NOT_FOUND, ERR_BOM_ENTRY_NOT_FOUND, ERR_APPROVAL_REQUEST_NOT_FOUND,
    ERR_OBLIGATION_TICKET_NOT_FOUND, ERR_VULNERABILITY_FINDING_NOT_FOUND,
    ERR_RELEASE_GATE_NOT_FOUND, ERR_REMEDIATION_PLAN_NOT_FOUND,
    ERR_AUDIT_ENGAGEMENT_NOT_FOUND,
)
from middleware import get_auth
from response import success_obj, success_list, parse_pagination
from services.policy import effective_classification
from routes.products import product_view
from routes.components import component_view
from routes.scans import scan_view
from routes.boms import bom_view, entry_view
from routes.approvals import approval_view
from routes.tickets import ticket_view
from routes.vulnerabilities import finding_view
from routes.gates import gate_view
from routes.plans import plan_view
from routes.engagements import engagement_view

bp = Blueprint("standalone", __name__)


def _paginate(items, args, view):
    limit, offset = parse_pagination(args)
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([view(i) for i in page], limit, offset, total)


# --- Standalone detail endpoints ---

@bp.route("/oss-products/products/<productId>", methods=["GET"])
def get_product_by_id(productId):
    get_auth()
    p = store.products.get(productId)
    if not p:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    return success_obj(product_view(p))


@bp.route("/oss-products/components/<componentId>", methods=["GET"])
def get_component_by_id(componentId):
    get_auth()
    c = store.components.get(componentId)
    if not c:
        raise err(ERR_COMPONENT_NOT_FOUND, "Component not found")
    return success_obj(component_view(c))


@bp.route("/oss-products/dependency-scans/<scanId>", methods=["GET"])
def get_scan_by_id(scanId):
    get_auth()
    s = store.scans.get(scanId)
    if not s:
        raise err(ERR_SCAN_NOT_FOUND, "DependencyScan not found")
    return success_obj(scan_view(s))


@bp.route("/oss-products/boms/<bomId>", methods=["GET"])
def get_bom_by_id(bomId):
    get_auth()
    b = store.boms.get(bomId)
    if not b:
        raise err(ERR_BOM_NOT_FOUND, "BillOfMaterials not found")
    return success_obj(bom_view(b))


@bp.route("/oss-products/bom-entries/<entryId>", methods=["GET"])
def get_entry_by_id(entryId):
    get_auth()
    e = store.bom_entries.get(entryId)
    if not e:
        raise err(ERR_BOM_ENTRY_NOT_FOUND, "BomEntry not found")
    return success_obj(entry_view(e))


@bp.route("/oss-products/license-approvals/<requestId>", methods=["GET"])
def get_approval_by_id(requestId):
    get_auth()
    a = store.approvals.get(requestId)
    if not a:
        raise err(ERR_APPROVAL_REQUEST_NOT_FOUND, "LicenseApprovalRequest not found")
    return success_obj(approval_view(a))


@bp.route("/oss-products/obligation-tickets/<ticketId>", methods=["GET"])
def get_ticket_by_id(ticketId):
    get_auth()
    t = store.tickets.get(ticketId)
    if not t:
        raise err(ERR_OBLIGATION_TICKET_NOT_FOUND, "ObligationTicket not found")
    return success_obj(ticket_view(t))


@bp.route("/oss-products/vulnerability-findings/<findingId>", methods=["GET"])
def get_finding_by_id(findingId):
    get_auth()
    f = store.findings.get(findingId)
    if not f:
        raise err(ERR_VULNERABILITY_FINDING_NOT_FOUND, "VulnerabilityFinding not found")
    return success_obj(finding_view(f))


@bp.route("/oss-products/release-gates/<gateId>", methods=["GET"])
def get_gate_by_id(gateId):
    get_auth()
    g = store.gates.get(gateId)
    if not g:
        raise err(ERR_RELEASE_GATE_NOT_FOUND, "ReleaseGate not found")
    return success_obj(gate_view(g))


@bp.route("/oss-products/remediation-plans/<planId>", methods=["GET"])
def get_plan_by_id(planId):
    get_auth()
    p = store.plans.get(planId)
    if not p:
        raise err(ERR_REMEDIATION_PLAN_NOT_FOUND, "RemediationPlan not found")
    return success_obj(plan_view(p))


@bp.route("/oss-products/audit-engagements/<engagementId>", methods=["GET"])
def get_engagement_by_id(engagementId):
    get_auth()
    e = store.engagements.get(engagementId)
    if not e:
        raise err(ERR_AUDIT_ENGAGEMENT_NOT_FOUND, "AuditEngagement not found")
    return success_obj(engagement_view(e))


# --- Flat filtered-list endpoints ---

@bp.route("/oss-products/dependency-scans", methods=["GET"])
def list_all_scans():
    get_auth()
    items = list(store.scans.values())
    pid = request.args.get("product_id")
    if pid:
        items = [s for s in items if s["product_id"] == pid]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    return _paginate(items, request.args, scan_view)


@bp.route("/oss-products/boms", methods=["GET"])
def list_all_boms():
    get_auth()
    items = list(store.boms.values())
    pid = request.args.get("product_id")
    if pid:
        items = [b for b in items if b["product_id"] == pid]
    sid = request.args.get("scan_id")
    if sid:
        items = [b for b in items if b["scan_id"] == sid]
    status = request.args.get("status")
    if status:
        items = [b for b in items if b["status"] == status]
    return _paginate(items, request.args, bom_view)


@bp.route("/oss-products/bom-entries", methods=["GET"])
def list_all_entries():
    get_auth()
    items = list(store.bom_entries.values())
    bid = request.args.get("bom_id")
    if bid:
        items = [e for e in items if e["bom_id"] == bid]
    cid = request.args.get("component_id")
    if cid:
        items = [e for e in items if e["component_id"] == cid]
    peid = request.args.get("parent_entry_id")
    if peid:
        items = [e for e in items if e.get("parent_entry_id") == peid]
    eff = request.args.get("effective_classification")
    if eff:
        items = [e for e in items
                 if (effective_classification(store.components.get(e["component_id"]))
                     if store.components.get(e["component_id"]) else None) == eff]
    return _paginate(items, request.args, entry_view)


@bp.route("/oss-products/license-approvals", methods=["GET"])
def list_all_approvals():
    get_auth()
    items = list(store.approvals.values())
    for param, field in (("product_id", "product_id"), ("component_id", "component_id"),
                         ("bom_entry_id", "bom_entry_id"), ("status", "status")):
        val = request.args.get(param)
        if val:
            items = [a for a in items if a.get(field) == val]
    return _paginate(items, request.args, approval_view)


@bp.route("/oss-products/obligation-tickets", methods=["GET"])
def list_all_tickets():
    get_auth()
    items = list(store.tickets.values())
    for param, field in (("product_id", "product_id"), ("bom_entry_id", "bom_entry_id"),
                         ("status", "status"), ("obligation_type", "obligation_type")):
        val = request.args.get(param)
        if val:
            items = [t for t in items if t.get(field) == val]
    return _paginate(items, request.args, ticket_view)


@bp.route("/oss-products/vulnerability-findings", methods=["GET"])
def list_all_findings():
    get_auth()
    items = list(store.findings.values())
    for param, field in (("product_id", "product_id"), ("bom_entry_id", "bom_entry_id"),
                         ("vulnerability_id", "vulnerability_id"), ("status", "status"),
                         ("remediation_component_id", "remediation_component_id")):
        val = request.args.get(param)
        if val:
            items = [f for f in items if f.get(field) == val]
    sev = request.args.get("severity")
    if sev:
        items = [f for f in items
                 if store.vulnerabilities.get(f["vulnerability_id"]) and
                 store.vulnerabilities[f["vulnerability_id"]]["severity"] == sev]
    return _paginate(items, request.args, finding_view)


@bp.route("/oss-products/release-gates", methods=["GET"])
def list_all_gates():
    get_auth()
    items = list(store.gates.values())
    for param, field in (("product_id", "product_id"), ("bom_id", "bom_id"),
                         ("gate_status", "gate_status")):
        val = request.args.get(param)
        if val:
            items = [g for g in items if g.get(field) == val]
    return _paginate(items, request.args, gate_view)


@bp.route("/oss-products/remediation-plans", methods=["GET"])
def list_all_plans():
    get_auth()
    items = list(store.plans.values())
    for param, field in (("product_id", "product_id"), ("finding_id", "finding_id"),
                         ("target_component_id", "target_component_id"),
                         ("verification_scan_id", "verification_scan_id"), ("status", "status")):
        val = request.args.get(param)
        if val:
            items = [p for p in items if p.get(field) == val]
    return _paginate(items, request.args, plan_view)


@bp.route("/oss-products/audit-engagements", methods=["GET"])
def list_all_engagements():
    get_auth()
    items = list(store.engagements.values())
    for param, field in (("product_id", "product_id"), ("status", "status")):
        val = request.args.get(param)
        if val:
            items = [e for e in items if e.get(field) == val]
    return _paginate(items, request.args, engagement_view)
