"""ReleaseGate endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import store, base_resource, touch, iso_fmt, parse_iso
from errors import (
    err, ERR_PRODUCT_NOT_FOUND, ERR_BOM_NOT_FOUND, ERR_RELEASE_GATE_NOT_FOUND,
    ERR_PRODUCT_BLOCKED, ERR_BOM_NOT_FINALIZED, ERR_GATE_NOT_EVALUABLE,
    ERR_GATE_NOT_BYPASSABLE, ERR_NOTICE_FILE_MISSING, ERR_STALE_VERSION,
    ERR_INVALID_REQUEST, ERR_APPROVAL_EXPIRED,
)
from middleware import require_roles, get_auth, get_json_body
from response import success_obj, success_list, parse_pagination
from services import engine
from services.policy import effective_classification, round2

bp = Blueprint("gates", __name__)


def gate_view(g):
    return {k: v for k, v in g.items() if not k.startswith("_")}


def _resolve(productId, gateId=None):
    p = store.products.get(productId)
    if not p:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    g = None
    if gateId is not None:
        g = store.gates.get(gateId)
        if not g or g["product_id"] != productId:
            raise err(ERR_RELEASE_GATE_NOT_FOUND, "ReleaseGate not found")
    return p, g


@bp.route("/oss-products/<productId>/release-gates", methods=["POST"])
def create_gate(productId):
    require_roles("ReleaseManager")
    p = store.products.get(productId)
    if not p:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    if p["compliance_posture"] == "BLOCKED":
        raise err(ERR_PRODUCT_BLOCKED, "Operation requires Product not in BLOCKED posture")
    body = get_json_body()
    bom_id = body.get("bom_id")
    release_version = body.get("release_version")
    if not bom_id:
        raise err(ERR_INVALID_REQUEST, "bom_id is required")
    if not release_version:
        raise err(ERR_INVALID_REQUEST, "release_version is required")
    bom = store.boms.get(bom_id)
    if not bom or bom["product_id"] != productId:
        raise err(ERR_BOM_NOT_FOUND, "BillOfMaterials not found")
    if bom["status"] != "FINALIZED":
        raise err(ERR_BOM_NOT_FINALIZED, "Operation requires BOM in FINALIZED status")

    g = base_resource()
    g.update({
        "product_id": productId,
        "bom_id": bom_id,
        "release_version": release_version,
        "gate_status": "OPEN",
        "evaluation_result": None,
        "blocking_findings_count": 0,
        "warning_findings_count": 0,
        "notice_file_attached": bool(bom.get("notice_file_generated")),
        "obligations_fulfilled_pct": 0.0,
        "bypass_reason": None,
        "bypass_approved_by": None,
        "evaluation_expires_at": None,
    })
    store.gates[g["id"]] = g
    return success_obj(gate_view(g), status=201)


@bp.route("/oss-products/<productId>/release-gates", methods=["GET"])
def list_gates(productId):
    get_auth()
    _resolve(productId)
    limit, offset = parse_pagination(request.args)
    items = [g for g in store.gates.values() if g["product_id"] == productId]
    gs = request.args.get("gate_status")
    if gs:
        items = [g for g in items if g["gate_status"] == gs]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([gate_view(g) for g in page], limit, offset, total)


@bp.route("/oss-products/<productId>/release-gates/<gateId>", methods=["GET"])
def get_gate(productId, gateId):
    get_auth()
    _, g = _resolve(productId, gateId)
    return success_obj(gate_view(g))


@bp.route("/oss-products/<productId>/release-gates/<gateId>/evaluate", methods=["POST"])
def evaluate_gate(productId, gateId):
    require_roles("ReleaseManager")
    p, g = _resolve(productId, gateId)
    body = get_json_body()
    bom = store.boms.get(g["bom_id"])
    if not bom:
        raise err(ERR_BOM_NOT_FOUND, "BillOfMaterials not found")
    if g["gate_status"] != "OPEN" or bom["status"] != "FINALIZED":
        raise err(ERR_GATE_NOT_EVALUABLE, "ReleaseGate must be OPEN and BOM must be FINALIZED")

    # OCC: expected_bom_version vs BOM version
    expected = body.get("expected_bom_version")
    if expected is not None:
        try:
            expected_int = int(expected)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "expected_bom_version must be an integer")
        if expected_int != bom["version"]:
            raise err(ERR_STALE_VERSION, "expected_version does not match current resource version (OCC conflict)")

    # Notice file presence
    notice_attached = bool(bom.get("notice_file_generated")) or bool(g.get("notice_file_attached"))
    if not notice_attached:
        raise err(ERR_NOTICE_FILE_MISSING, "Release gate evaluation requires NOTICE file generated")

    now = store.now()
    entries = engine.entries_of_bom(bom["id"])
    engine._attach_eff(entries)

    # Approval temporal validity (PRD §2.5 layer 9): an approval relied upon
    # past its expiry_at is no defense at gate evaluation. expiry_at is only
    # ever set by an approval decision, so this fires exactly for approvals
    # that were granted and have since lapsed (whether or not the clock sweep
    # has already flipped their status to EXPIRED).
    restricted_component_ids = {
        e["component_id"] for e in entries
        if e.get("_effective_classification") == "RESTRICTED"
    }
    for a in store.approvals.values():
        if a["product_id"] != productId:
            continue
        if a["component_id"] not in restricted_component_ids:
            continue
        exp = a.get("expiry_at")
        if exp and parse_iso(exp) < now:
            raise err(ERR_APPROVAL_EXPIRED,
                      "License approval request relied upon past its expiry_at")

    approved_ids = engine.approved_component_ids(productId)  # already filters expired

    # Compute counts
    blocking = 0
    warning = 0
    for e in entries:
        eff = e.get("_effective_classification")
        if eff == "PROHIBITED":
            blocking += 1
        elif eff == "RESTRICTED" and e["component_id"] not in approved_ids:
            warning += 1
    for f in store.findings.values():
        if f["product_id"] != productId:
            continue
        if f["status"] not in ("OPEN", "CONFIRMED"):
            continue
        entry = store.bom_entries.get(f["bom_entry_id"])
        if not entry or entry["bom_id"] != bom["id"]:
            continue
        vuln = store.vulnerabilities.get(f["vulnerability_id"])
        if not vuln:
            continue
        if vuln["severity"] == "CRITICAL":
            blocking += 1
        elif vuln["severity"] == "HIGH":
            warning += 1

    tickets = engine.tickets_of_bom(bom["id"])
    if tickets:
        done = sum(1 for t in tickets if t["status"] in ("FULFILLED", "WAIVED"))
        obligations_pct = round2(done * 100.0 / len(tickets))
    else:
        obligations_pct = 100.0

    g["gate_status"] = "EVALUATING"
    g["blocking_findings_count"] = blocking
    g["warning_findings_count"] = warning
    g["obligations_fulfilled_pct"] = obligations_pct
    g["notice_file_attached"] = True

    # Verdict ladder
    audit_active = any(
        e["product_id"] == productId and e["status"] in
        ("INITIATED", "SCOPING", "DATA_COLLECTION", "ANALYSIS", "REPORT_DRAFT")
        for e in store.engagements.values()
    )
    max_conditional = 3
    if p.get("distribution_model") == "EMBEDDED" or audit_active:
        max_conditional = 0

    if blocking > 0:
        result = "FAIL"
    elif obligations_pct < 100:
        result = "FAIL"
    elif warning > max_conditional:
        result = "FAIL"
    elif warning > 0:
        result = "CONDITIONAL_PASS"
    else:
        result = "PASS"

    # PRD §3.7: the verdict "moves the gate from `EVALUATING` to `FAILED`" (or
    # `PASSED`). The gate is now EVALUATING with the verdict recorded; the
    # system completes the transition to PASSED/FAILED (see the time sweep in
    # services/engine.py), which leaves the §3.7 CISO bypass — defined only
    # for a gate that is EVALUATING — exercisable.
    g["evaluation_result"] = result
    if result in ("PASS", "CONDITIONAL_PASS"):
        g["evaluation_expires_at"] = iso_fmt(now + timedelta(days=30))
    touch(g)
    return success_obj(gate_view(g))


@bp.route("/oss-products/<productId>/release-gates/<gateId>/bypass", methods=["POST"])
def bypass_gate(productId, gateId):
    user_id, _ = require_roles("CISO")
    p, g = _resolve(productId, gateId)
    body = get_json_body()
    reason = body.get("bypass_reason")
    if not reason:
        raise err(ERR_INVALID_REQUEST, "bypass_reason must be provided")
    if g["gate_status"] != "EVALUATING" or p["compliance_posture"] == "BLOCKED":
        raise err(ERR_GATE_NOT_BYPASSABLE, "ReleaseGate must be EVALUATING and Product must not be BLOCKED")
    g["gate_status"] = "BYPASSED"
    g["evaluation_result"] = "CONDITIONAL_PASS"
    g["bypass_reason"] = reason
    g["bypass_approved_by"] = user_id
    g["evaluation_expires_at"] = iso_fmt(store.now() + timedelta(days=7))
    touch(g)
    return success_obj(gate_view(g))
