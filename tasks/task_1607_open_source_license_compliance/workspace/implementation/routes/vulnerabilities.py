"""Vulnerability + VulnerabilityFinding endpoints."""

from flask import Blueprint, request

from db import store, base_resource, touch, iso_fmt
from errors import (
    err, ERR_PRODUCT_NOT_FOUND, ERR_VULNERABILITY_NOT_FOUND,
    ERR_VULNERABILITY_FINDING_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_FINDING_NOT_OPEN, ERR_FINDING_NOT_CONFIRMED, ERR_FINDING_NOT_REMEDIABLE,
)
from middleware import require_roles, get_auth, get_json_body
from response import success_obj, success_list, parse_pagination
from services import engine

bp = Blueprint("vulnerabilities", __name__)

SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def vuln_view(v):
    return {k: x for k, x in v.items() if not k.startswith("_")}


def finding_view(f):
    d = {k: x for k, x in f.items() if not k.startswith("_")}
    vuln = store.vulnerabilities.get(f["vulnerability_id"])
    d["severity"] = vuln["severity"] if vuln else None
    d["cve_id"] = vuln["cve_id"] if vuln else None
    return d


def _register_vulnerability(body):
    cve_id = body.get("cve_id")
    severity = body.get("severity")
    cvss_score = body.get("cvss_score")
    published_at = body.get("published_at")
    affected_package_url = body.get("affected_package_url")
    if not cve_id:
        raise err(ERR_INVALID_REQUEST, "cve_id is required")
    if severity not in SEVERITIES:
        raise err(ERR_INVALID_REQUEST, "severity must be LOW, MEDIUM, HIGH, or CRITICAL")
    if cvss_score is None:
        raise err(ERR_INVALID_REQUEST, "cvss_score is required")
    try:
        score = float(cvss_score)
    except (TypeError, ValueError):
        raise err(ERR_INVALID_REQUEST, "cvss_score must be a number between 0.0 and 10.0")
    if score < 0.0 or score > 10.0:
        raise err(ERR_INVALID_REQUEST, "cvss_score must be a number between 0.0 and 10.0")
    if not published_at:
        raise err(ERR_INVALID_REQUEST, "published_at is required")
    if not affected_package_url:
        raise err(ERR_INVALID_REQUEST, "affected_package_url is required")

    v = base_resource()
    v.update({
        "cve_id": cve_id,
        "severity": severity,
        "cvss_score": score,
        "published_at": published_at,
        "affected_package_url": affected_package_url,
        "fixed_in_version": body.get("fixed_in_version"),
        "license_change_flag": bool(body.get("license_change_flag", False)),
        "new_license_spdx": body.get("new_license_spdx"),
    })
    store.vulnerabilities[v["id"]] = v
    engine.propagate_vulnerability(v)
    return v


@bp.route("/oss-vulnerabilities", methods=["POST"])
def create_vulnerability():
    require_roles("SecurityAnalyst")
    body = get_json_body()
    v = _register_vulnerability(body)
    return success_obj(vuln_view(v), status=201)


@bp.route("/oss-vulnerabilities", methods=["GET"])
def list_vulnerabilities():
    get_auth()
    limit, offset = parse_pagination(request.args)
    items = sorted(store.vulnerabilities.values(), key=lambda x: (x["created_at"], x["id"]))
    sev = request.args.get("severity")
    if sev:
        items = [v for v in items if v["severity"] == sev]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([vuln_view(v) for v in page], limit, offset, total)


@bp.route("/oss-vulnerabilities/<vulnerabilityId>", methods=["GET"])
def get_vulnerability(vulnerabilityId):
    get_auth()
    v = store.vulnerabilities.get(vulnerabilityId)
    if not v:
        raise err(ERR_VULNERABILITY_NOT_FOUND, "Vulnerability not found")
    return success_obj(vuln_view(v))


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

def _resolve_finding(productId, findingId=None):
    p = store.products.get(productId)
    if not p:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    f = None
    if findingId is not None:
        f = store.findings.get(findingId)
        if not f or f["product_id"] != productId:
            raise err(ERR_VULNERABILITY_FINDING_NOT_FOUND, "VulnerabilityFinding not found")
    return p, f


@bp.route("/oss-products/<productId>/vulnerability-findings", methods=["GET"])
def list_findings(productId):
    get_auth()
    _resolve_finding(productId)
    limit, offset = parse_pagination(request.args)
    items = [f for f in store.findings.values() if f["product_id"] == productId]
    status = request.args.get("status")
    if status:
        items = [f for f in items if f["status"] == status]
    sev = request.args.get("severity")
    if sev:
        items = [f for f in items
                 if store.vulnerabilities.get(f["vulnerability_id"]) and
                 store.vulnerabilities[f["vulnerability_id"]]["severity"] == sev]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([finding_view(f) for f in page], limit, offset, total)


@bp.route("/oss-products/<productId>/vulnerability-findings/<findingId>", methods=["GET"])
def get_finding(productId, findingId):
    get_auth()
    _, f = _resolve_finding(productId, findingId)
    return success_obj(finding_view(f))


@bp.route("/oss-products/<productId>/vulnerability-findings/<findingId>/confirm", methods=["POST"])
def confirm_finding(productId, findingId):
    require_roles("SecurityAnalyst")
    p, f = _resolve_finding(productId, findingId)
    if f["status"] != "OPEN":
        raise err(ERR_FINDING_NOT_OPEN, "VulnerabilityFinding must be OPEN")
    f["status"] = "CONFIRMED"
    vuln = store.vulnerabilities.get(f["vulnerability_id"])
    f["remediation_deadline"] = iso_fmt(engine.compute_remediation_deadline(f, vuln, p))
    touch(f)
    if vuln and vuln["severity"] == "CRITICAL":
        if p["compliance_posture"] == "COMPLIANT":
            engine.set_posture(p, "AT_RISK")
    engine.recompute_product_counts(p)
    engine.reevaluate_product_posture(p)
    return success_obj(finding_view(f))


@bp.route("/oss-products/<productId>/vulnerability-findings/<findingId>/mitigate", methods=["POST"])
def mitigate_finding(productId, findingId):
    require_roles("SecurityAnalyst")
    p, f = _resolve_finding(productId, findingId)
    if f["status"] != "CONFIRMED":
        raise err(ERR_FINDING_NOT_CONFIRMED, "VulnerabilityFinding must be CONFIRMED")
    f["status"] = "MITIGATED"
    touch(f)
    engine.recompute_product_counts(p)
    engine.reevaluate_product_posture(p)
    return success_obj(finding_view(f))


@bp.route("/oss-products/<productId>/vulnerability-findings/<findingId>/verify-remediation", methods=["POST"])
def verify_remediation(productId, findingId):
    require_roles("SecurityAnalyst")
    p, f = _resolve_finding(productId, findingId)
    body = get_json_body()
    evidence = body.get("verification_evidence_uri")
    if not evidence:
        raise err(ERR_INVALID_REQUEST, "verification_evidence_uri must be provided")
    if f["status"] not in ("CONFIRMED", "MITIGATED"):
        raise err(ERR_FINDING_NOT_REMEDIABLE, "VulnerabilityFinding must be CONFIRMED or MITIGATED")
    if f.get("remediation_status") != "VERIFIED":
        raise err(ERR_FINDING_NOT_REMEDIABLE, "VulnerabilityFinding must be CONFIRMED or MITIGATED")
    f["status"] = "REMEDIATED"
    f["verification_evidence_uri"] = evidence
    touch(f)
    entry = store.bom_entries.get(f["bom_entry_id"])
    if entry:
        engine.recompute_entry_vuln_max(entry)
    engine.recompute_product_counts(p)
    engine.reevaluate_product_posture(p)
    return success_obj(finding_view(f))


@bp.route("/oss-products/<productId>/vulnerability-findings/<findingId>/mark-false-positive", methods=["POST"])
def mark_false_positive(productId, findingId):
    require_roles("SecurityAnalyst")
    p, f = _resolve_finding(productId, findingId)
    if f["status"] != "OPEN":
        raise err(ERR_FINDING_NOT_OPEN, "VulnerabilityFinding must be OPEN")
    f["status"] = "FALSE_POSITIVE"
    touch(f)
    entry = store.bom_entries.get(f["bom_entry_id"])
    if entry:
        engine.recompute_entry_vuln_max(entry)
    engine.recompute_product_counts(p)
    engine.reevaluate_product_posture(p)
    return success_obj(finding_view(f))


@bp.route("/oss-products/<productId>/vulnerability-findings/<findingId>/wont-fix", methods=["POST"])
def wont_fix(productId, findingId):
    user_id, _ = require_roles("CISO")
    p, f = _resolve_finding(productId, findingId)
    body = get_json_body()
    rationale = body.get("risk_acceptance_rationale")
    if not rationale:
        raise err(ERR_INVALID_REQUEST, "risk_acceptance_rationale is required")
    if f["status"] not in ("OPEN", "CONFIRMED"):
        raise err(ERR_FINDING_NOT_OPEN, "VulnerabilityFinding must be OPEN")
    f["status"] = "WONT_FIX"
    f["risk_acceptance_rationale"] = rationale
    touch(f)
    entry = store.bom_entries.get(f["bom_entry_id"])
    if entry:
        engine.recompute_entry_vuln_max(entry)
    engine.recompute_product_counts(p)
    engine.reevaluate_product_posture(p)
    return success_obj(finding_view(f))
