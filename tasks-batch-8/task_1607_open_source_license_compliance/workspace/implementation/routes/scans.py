"""DependencyScan endpoints."""

import json

from flask import Blueprint, request

from db import store, base_resource, touch
from errors import (
    err, ERR_PRODUCT_NOT_FOUND, ERR_SCAN_NOT_FOUND, ERR_INVALID_SCAN_TOOL,
    ERR_PRODUCT_BLOCKED, ERR_STALE_VERSION, ERR_SCAN_NOT_CANCELLABLE,
    ERR_INVALID_REQUEST, ERR_PROHIBITED_COMPONENT,
)
from middleware import require_roles, get_auth, get_json_body
from response import success_obj, success_list, parse_pagination
from services import engine
from services.engine import sha256_hex
from services.policy import classify_license

bp = Blueprint("scans", __name__)

SCAN_TOOLS = {"SYFT", "ORT", "SCANCODE", "FOSSOLOGY", "COMMERCIAL_VENDOR_X"}
SCAN_SCOPES = {"FULL", "INCREMENTAL", "TRANSITIVE", "DIRECT_ONLY"}


def scan_view(s):
    return {k: v for k, v in s.items() if not k.startswith("_")}


@bp.route("/oss-products/<productId>/dependency-scans", methods=["POST"])
def create_scan(productId):
    require_roles("ComplianceAnalyst")
    p = store.products.get(productId)
    if not p:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    if p["compliance_posture"] == "BLOCKED":
        raise err(ERR_PRODUCT_BLOCKED, "Operation requires Product not in BLOCKED posture")
    body = get_json_body()
    scan_tool = body.get("scan_tool")
    if scan_tool not in SCAN_TOOLS:
        raise err(ERR_INVALID_SCAN_TOOL,
                  "scan_tool must be one of SYFT, ORT, SCANCODE, FOSSOLOGY, COMMERCIAL_VENDOR_X")
    scan_scope = body.get("scan_scope")
    if scan_scope is not None and scan_scope not in SCAN_SCOPES:
        raise err(ERR_INVALID_REQUEST, "scan_scope must be FULL, INCREMENTAL, TRANSITIVE, or DIRECT_ONLY")

    # OCC: expected_product_version vs posture_version
    expected = body.get("expected_product_version")
    if expected is not None:
        try:
            expected_int = int(expected)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "expected_product_version must be an integer")
        if expected_int != p["posture_version"]:
            raise err(ERR_STALE_VERSION, "expected_version does not match current resource version (OCC conflict)")

    manifest = body.get("manifest_components") or body.get("components") or []
    if not isinstance(manifest, list):
        raise err(ERR_INVALID_REQUEST, "manifest_components must be an array")

    # Prohibited-content safety: refuse manifests containing prohibited components (per declared license)
    for spec in manifest:
        lic = spec.get("declared_license_spdx") or spec.get("license")
        cls = classify_license(lic, p.get("distribution_model"))
        if cls == "PROHIBITED":
            raise err(ERR_PROHIBITED_COMPONENT,
                      "Component has PROHIBITED classification and cannot be added without CISO waiver")

    s = base_resource()
    manifest_hash = sha256_hex(json.dumps(manifest, sort_keys=True))
    s.update({
        "product_id": productId,
        "scan_tool": scan_tool,
        "scan_scope": scan_scope,
        "status": "QUEUED",
        "raw_manifest_hash": manifest_hash,
        "components_discovered": 0,
        "components_resolved": 0,
        "license_scan_coverage_pct": 0.0,
        "_manifest_components": manifest,
        "_version_label": body.get("version_label"),
    })
    store.scans[s["id"]] = s

    # Scan creation advances the product's posture_version (OCC)
    p["posture_version"] = int(p.get("posture_version", 1)) + 1
    touch(p)

    return success_obj(scan_view(s), status=201)


@bp.route("/oss-products/<productId>/dependency-scans", methods=["GET"])
def list_scans(productId):
    get_auth()
    p = store.products.get(productId)
    if not p:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    limit, offset = parse_pagination(request.args)
    items = [s for s in store.scans.values() if s["product_id"] == productId]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([scan_view(s) for s in page], limit, offset, total)


@bp.route("/oss-products/<productId>/dependency-scans/<scanId>", methods=["GET"])
def get_scan(productId, scanId):
    get_auth()
    p = store.products.get(productId)
    if not p:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    s = store.scans.get(scanId)
    if not s or s["product_id"] != productId:
        raise err(ERR_SCAN_NOT_FOUND, "DependencyScan not found")
    return success_obj(scan_view(s))


@bp.route("/oss-products/<productId>/dependency-scans/<scanId>/cancel", methods=["POST"])
def cancel_scan(productId, scanId):
    require_roles("ComplianceAnalyst")
    p = store.products.get(productId)
    if not p:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    s = store.scans.get(scanId)
    if not s or s["product_id"] != productId:
        raise err(ERR_SCAN_NOT_FOUND, "DependencyScan not found")
    if s["status"] not in ("QUEUED", "PARSING"):
        raise err(ERR_SCAN_NOT_CANCELLABLE, "Scan must be in QUEUED or PARSING state to cancel")
    s["status"] = "CANCELLED"
    touch(s)
    return success_obj(scan_view(s))
